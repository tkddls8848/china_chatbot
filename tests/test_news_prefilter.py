import asyncio
import json
from datetime import date, timedelta

from features.news_prefilter.matcher import StockEntityMatcher
from features.news_prefilter.optimizer import (
    FEATURE_NAMES,
    TrainingSample,
    optimize_for_cpu_budget,
    predict_probability,
)
from features.news_prefilter.service import NewsPrefilter, _rank_auc
from news.sources import GlobalArticle


class _StockDb:
    def get_candidate_universe(self):
        return [
            {
                "code": "US:NASDAQ:AAPL",
                "display_name": "Apple Inc",
                "cn_name": "苹果公司",
                "ko_name": "애플",
                "market": "US",
            },
            {
                "code": "US:NYSE:BH",
                "display_name": "Better Home Holdings",
                "cn_name": "",
                "ko_name": "",
                "market": "US",
            },
            {
                "code": "KR:KOSPI:000660",
                "display_name": "이닉스",
                "cn_name": "",
                "ko_name": "이닉스",
                "market": "KR",
            },
        ]


def _observations(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def _service(tmp_path, *, mode="shadow", exploration_slots=0, translate_limit=2):
    return NewsPrefilter(
        stock_db=_StockDb(),
        event_file=tmp_path / "events.json",
        observation_file=tmp_path / "observations.jsonl",
        model_file=tmp_path / "model.json",
        cpu_state_file=tmp_path / "cpu.json",
        mode=mode,
        event_window_hours=72,
        max_events=100,
        observation_retention_days=14,
        similarity_threshold=0.7,
        exploration_slots=exploration_slots,
        translate_limit=translate_limit,
        daily_cpu_budget_seconds=100,
    )


def _article(index, title, content="본문"):
    return GlobalArticle(
        article_id=f"article-{index}",
        title=title,
        content=content,
        published_at=f"2026-08-16 10:0{index}:00",
    )


def test_aho_matcher_preserves_name_matching_rules():
    matcher = StockEntityMatcher(_StockDb().get_candidate_universe())

    assert matcher.match("Apple earnings guidance").codes == {"US:NASDAQ:AAPL"}
    assert matcher.match("Better housing data").codes == set()
    assert matcher.match("Better Home earnings").codes == {"US:NYSE:BH"}
    assert matcher.match("SK하이닉스 실적").codes == set()
    assert matcher.match("이닉스 실적").codes == {"KR:KOSPI:000660"}
    assert matcher.match("苹果公司发布业绩").codes == {"US:NASDAQ:AAPL"}


def test_shadow_mode_records_scores_but_keeps_feed_order(tmp_path):
    service = _service(tmp_path, mode="shadow")
    articles = [
        _article(0, "일반 시장 소식"),
        _article(1, "Apple earnings guidance raised"),
        _article(2, "Apple earnings guidance raised again"),
    ]

    ranked = asyncio.run(
        service.rank_articles(
            source="gnews_us",
            market="US",
            articles=articles,
            watchlist={"US:NASDAQ:AAPL": "애플"},
            cycle_id="cycle-1",
        )
    )

    assert [row.article.article_id for row in ranked] == [
        "article-0",
        "article-1",
        "article-2",
    ]
    assert ranked[1].score > ranked[0].score
    records = _observations(tmp_path)
    assert all(record["mode"] == "shadow" for record in records)
    # 남기는 것은 두 정책이 고르는 기사의 합집합이다. 여기서는 최신순이
    # {0,1}, 사전선별이 {1,2}라 셋 다 남고, 두 정책의 불일치가 그대로 보인다.
    candidates = [record for record in records if record["type"] == "candidate"]
    assert all(
        record["latest_selected"] or record["prefilter_selected"]
        for record in candidates
    )
    assert {record["feed_rank"] for record in candidates if record["latest_selected"]} == {0, 1}
    assert {
        record["feed_rank"] for record in candidates if record["prefilter_selected"]
    } == {1, 2}
    # 남기지 않은 후보도 주기 집계에는 전부 잡힌다.
    cycle = next(record for record in records if record["type"] == "cycle")
    assert cycle["candidates"] == 3
    assert cycle["logged"] == len(candidates)


def test_active_mode_uses_prefilter_order_without_adding_translation_slots(tmp_path):
    service = _service(tmp_path, mode="active", translate_limit=2)
    articles = [
        _article(0, "일반 시장 소식"),
        _article(1, "Apple earnings guidance raised"),
        _article(2, "또 다른 일반 소식"),
    ]

    ranked = asyncio.run(
        service.rank_articles(
            source="gnews_us",
            market="US",
            articles=articles,
            watchlist={"US:NASDAQ:AAPL": "애플"},
            cycle_id="cycle-1",
        )
    )

    assert ranked[0].article.article_id == "article-1"
    assert sum(row.prefilter_rank < 2 for row in ranked) == 2
    assert sum(row.exploration for row in ranked) == 0


def test_outcome_is_joinable_to_original_candidate(tmp_path):
    service = _service(tmp_path)
    ranked = asyncio.run(
        service.rank_articles(
            source="gnews_us",
            market="US",
            articles=[_article(0, "Apple earnings")],
            watchlist={},
            cycle_id="cycle-1",
        )
    )
    asyncio.run(
        service.record_outcome(
            candidate_id=ranked[0].candidate_id,
            impact="high",
            sentiment=0.7,
        )
    )

    records = _observations(tmp_path)
    assert [record["type"] for record in records] == ["candidate", "cycle", "outcome"]
    assert records[0]["candidate_id"] == records[2]["candidate_id"]

    # 라벨은 candidate와 outcome을 이어야 나온다.
    samples = service._load_training_samples()
    assert [(sample.label, sample.title) for sample in samples] == [(1, "Apple earnings")]


def test_training_samples_are_read_incrementally(tmp_path):
    """관측 파일은 offset 뒤만 이어 읽는다.

    보존 기간이 차면 파일이 수백 MB가 되므로, 매번 전체를 dict에 담으면
    1GB 인스턴스가 학습을 시작하기 전에 죽는다.
    """
    service = _service(tmp_path)

    def observe(index):
        ranked = asyncio.run(
            service.rank_articles(
                source="gnews_us",
                market="US",
                articles=[_article(index, f"Apple earnings {index}")],
                watchlist={},
                cycle_id=f"cycle-{index}",
            )
        )
        asyncio.run(
            service.record_outcome(
                candidate_id=ranked[0].candidate_id, impact="high", sentiment=0.5
            )
        )

    observe(0)
    assert len(service._load_training_samples()) == 1
    consumed = service._samples_offset
    assert consumed == (tmp_path / "observations.jsonl").stat().st_size

    observe(1)
    # 두 번째 호출은 새로 덧붙은 줄만 읽고 이전 샘플을 그대로 들고 있다.
    samples = service._load_training_samples()
    assert len(samples) == 2
    assert service._samples_offset > consumed

    # 파일이 줄면(압축·교체) 처음부터 다시 만든다.
    (tmp_path / "observations.jsonl").write_text("", encoding="utf-8")
    assert service._load_training_samples() == []
    assert service._samples_offset == 0


def test_pending_candidates_stay_bounded(tmp_path):
    """outcome이 끝내 오지 않는 후보가 무한히 쌓이지 않는다."""
    service = _service(tmp_path)
    for index in range(service_pending_limit() + 50):
        service._consume_observation(
            {
                "type": "candidate",
                "candidate_id": f"c{index}",
                "observed_at": "2026-08-16T10:00:00+09:00",
                "title": "t",
                "features": {name: 0.0 for name in FEATURE_NAMES},
            }
        )
    assert len(service._pending_candidates) == service_pending_limit()
    # 가장 오래된 것부터 밀려난다.
    assert "c0" not in service._pending_candidates


def service_pending_limit():
    from features.news_prefilter.service import _PENDING_CANDIDATE_LIMIT

    return _PENDING_CANDIDATE_LIMIT


def test_report_separates_policy_disagreement_from_discrimination(tmp_path):
    service = _service(tmp_path, translate_limit=2)
    ranked = asyncio.run(
        service.rank_articles(
            source="gnews_us",
            market="US",
            articles=[
                _article(0, "일반 시장 소식"),
                _article(1, "Apple earnings guidance raised"),
                _article(2, "Apple earnings guidance raised again"),
            ],
            watchlist={"US:NASDAQ:AAPL": "애플"},
            cycle_id="cycle-1",
        )
    )
    # shadow에서 실제로 번역되는 것은 최신순 상위 2건뿐이라 라벨도 거기에만 붙는다.
    for row, impact in zip(ranked[:2], ("low", "high")):
        asyncio.run(
            service.record_outcome(
                candidate_id=row.candidate_id, impact=impact, sentiment=0.4
            )
        )

    report = asyncio.run(service.report())

    assert report["mode"] == "shadow"
    assert report["cycles"] == 1
    assert report["candidates_seen"] == 3
    # 최신순은 {0,1}, 사전선별은 {1,2} — 겹치는 1건과 각자 1건씩.
    assert (report["agree"], report["latest_only"], report["prefilter_only"]) == (1, 1, 1)
    assert report["labeled"] == 2
    assert report["positives"] == 1
    # 점수가 높은 쪽이 high였으므로 완전 분리.
    assert report["auc"] == 1.0


def test_report_auc_is_undefined_without_both_labels(tmp_path):
    """양성만 있으면 AUC를 1.0으로 보고하지 않는다."""
    service = _service(tmp_path)
    ranked = asyncio.run(
        service.rank_articles(
            source="gnews_us",
            market="US",
            articles=[_article(0, "Apple earnings")],
            watchlist={},
            cycle_id="cycle-1",
        )
    )
    asyncio.run(
        service.record_outcome(
            candidate_id=ranked[0].candidate_id, impact="high", sentiment=0.4
        )
    )

    report = asyncio.run(service.report())

    assert report["labeled"] == 1
    assert report["auc"] is None


def test_rank_auc_treats_ties_as_random():
    """모델이 없어 점수가 모두 같으면 0.5여야 한다."""
    assert _rank_auc([(1.0, 1), (1.0, 0), (1.0, 1), (1.0, 0)]) == 0.5
    assert _rank_auc([(2.0, 1), (1.0, 0)]) == 1.0
    assert _rank_auc([(1.0, 1), (2.0, 0)]) == 0.0


def test_stale_validation_ap_does_not_block_updates():
    """다른 split에서 잰 옛 AP가 갱신을 영구히 막지 않는다.

    날짜가 쌓이면 walk-forward test set이 바뀐다. 저장된 값을 그대로 기준선으로
    쓰면 우연히 쉬운 split에서 나온 1.0 하나로 모델이 다시는 갱신되지 않는다.
    """
    samples = [
        TrainingSample(
            day=f"2026-08-{1 + index // 25:02d}",
            title="Apple earnings beat" if index % 2 else "일반 소식",
            features={name: float(index % 2) for name in FEATURE_NAMES},
            label=index % 2,
        )
        for index in range(200)
    ]
    stale = {
        "weights": [0.0] * (len(FEATURE_NAMES) + 2048),
        "intercept": 0.0,
        "validation_ap": 1.0,  # 옛 split에서 잰 도달 불가능한 값
    }

    result = optimize_for_cpu_budget(samples, stale, 1.0)

    assert result.trials > 0
    assert result.model is not None


def test_cpu_budget_counts_foreground_and_background_together(tmp_path):
    service = _service(tmp_path)
    service._cpu_state["foreground_cpu_seconds"] = 20.0
    service.record_background_cpu(55.0)

    status = service.cpu_status()

    assert status["used_seconds"] == 75.0
    assert status["remaining_seconds"] == 25.0
    persisted = json.loads((tmp_path / "cpu.json").read_text(encoding="utf-8"))
    assert persisted["reserve_ratio"] == 0.25


def test_optimizer_trains_on_original_titles_with_time_split():
    start = date(2026, 8, 1)
    samples = []
    for day_offset in range(6):
        for index in range(30):
            positive = index % 2 == 0
            features = {name: 0.0 for name in FEATURE_NAMES}
            features["headline_signal"] = float(positive)
            samples.append(
                TrainingSample(
                    day=(start + timedelta(days=day_offset)).isoformat(),
                    title=(
                        f"Company earnings beat estimates {index}"
                        if positive
                        else f"Routine market update {index}"
                    ),
                    features=features,
                    label=int(positive),
                )
            )

    result = optimize_for_cpu_budget(samples, None, 0.05)

    assert result.trials >= 1
    assert result.model is not None
    assert result.model["validation_ap"] > result.model["validation_prevalence"]
    assert predict_probability(
        result.model,
        "Company earnings beat estimates",
        {name: float(name == "headline_signal") for name in FEATURE_NAMES},
    ) > predict_probability(
        result.model,
        "Routine market update",
        {name: 0.0 for name in FEATURE_NAMES},
    )

