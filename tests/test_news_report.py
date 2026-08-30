"""매시간 원문 수집과 3시간 시장상황 보고서."""

import asyncio
import json
from datetime import datetime

import pytest

from core.clock import JST
from features.news import feature as news_feature
from llm.news_report import NewsReportAnalyzer, NewsReportError
from news.report import (
    collect_report_source,
    format_market_section,
    group_by_market,
    send_news_report,
)
from news.registry import SourceSpec
from news.sources import GlobalArticle
from state import NewsReportQueue, SentNewsTracker


class _RecordingBot:
    def __init__(self, fail=False):
        self.messages = []
        self._fail = fail

    async def send_message(self, chat_id, text, parse_mode=None):
        if self._fail:
            raise RuntimeError("telegram down")
        self.messages.append(text)


class _FailOnCallBot:
    def __init__(self, fail_on: int):
        self.calls = 0
        self.messages = []
        self._fail_on = fail_on

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls += 1
        if self.calls == self._fail_on:
            raise RuntimeError("telegram down")
        self.messages.append(text)


class _RecordingTracker:
    def __init__(self, reservable=True):
        self.confirmed = []
        self.released = []
        self.reserved = []
        self._reservable = reservable

    async def reserve(self, article_id):
        if not self._reservable:
            return False
        self.reserved.append(article_id)
        return True

    async def confirm(self, article_id):
        self.confirmed.append(article_id)

    async def release(self, article_id):
        self.released.append(article_id)

    async def persist(self):
        return None


class _RecordingLog:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


class _FakeBackend:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, max_tokens, temperature):
        if self.error is not None:
            raise self.error
        self.calls.append(json.loads(user_prompt))
        return json.dumps(self.payload, ensure_ascii=False)


class _App:
    def __init__(self, **bot_data):
        self.bot = bot_data.pop("bot", _RecordingBot())
        self.bot_data = bot_data


class _RecordingScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, **kwargs):
        self.jobs.append((func, kwargs))


def _analyzer(tmp_path, payload=None, error=None, max_highlights=8):
    return NewsReportAnalyzer(
        backend=_FakeBackend(payload, error),
        prompt_file=_prompt_file(),
        num_predict=2048,
        max_highlights=max_highlights,
    )


def _prompt_file():
    from core.config import NEWS_REPORT_PROMPT_FILE

    return NEWS_REPORT_PROMPT_FILE


def _queue(tmp_path, per_source_limit=12, max_items=600):
    return NewsReportQueue(
        tmp_path / "news_report_queue.json",
        per_source_limit=per_source_limit,
        max_items=max_items,
    )


def _item(index, *, market="US", event_id=""):
    return {
        "article_id": f"gnews_us-{index}",
        "event_id": event_id or f"event-{index}",
        "source": "gnews_us",
        "label": "구글뉴스",
        "market": market,
        "title": f"Headline {index}",
        "url": "",
        "published_at": f"2026-08-18 0{index}:10:00",
        "published_date": "",
        "prefilter_candidate_id": "",
    }


def _payload(analysis="현재 시장상황 요약이다.", indexes=(0,)):
    return {
        "analysis": analysis,
        "highlights": [
            {
                "index": index,
                "title": f"한국어 제목 {index}",
                "sentiment": 0.4,
                "impact": "high",
                "mentioned_stocks": ["AAPL"],
            }
            for index in indexes
        ],
    }


# ── 큐 ────────────────────────────────────────────────

def test_queue_rejects_duplicate_articles_and_events(tmp_path):
    queue = _queue(tmp_path)

    accepted = asyncio.run(queue.enqueue([_item(0), _item(0), _item(1, event_id="event-0")]))

    # 같은 기사도, 같은 사건을 옮겨 적은 다른 기사도 한 번만 담는다.
    assert [row["article_id"] for row in accepted] == ["gnews_us-0"]


def test_queue_caps_one_source_per_cycle(tmp_path):
    queue = _queue(tmp_path, per_source_limit=2)

    accepted = asyncio.run(queue.enqueue([_item(index) for index in range(5)]))

    assert len(accepted) == 2


def test_queue_survives_a_restart(tmp_path):
    asyncio.run(_queue(tmp_path).enqueue([_item(0), _item(1)]))

    opened_at, items = asyncio.run(_queue(tmp_path).snapshot())

    assert opened_at
    assert [row["article_id"] for row in items] == ["gnews_us-0", "gnews_us-1"]


def test_queue_drops_the_oldest_when_full(tmp_path):
    queue = _queue(tmp_path, max_items=2)

    asyncio.run(queue.enqueue([_item(0), _item(1)]))
    asyncio.run(queue.enqueue([_item(2)]))

    _, items = asyncio.run(queue.snapshot())
    assert [row["article_id"] for row in items] == ["gnews_us-1", "gnews_us-2"]


@pytest.mark.xfail(
    strict=True,
    reason="queue overflow does not release or confirm the evicted tracker reservation",
)
def test_queue_overflow_does_not_leave_evicted_article_pending(tmp_path):
    """큐에서 밀려난 기사는 tracker의 처리 중 상태에도 남으면 안 된다."""
    tracker = SentNewsTracker(tmp_path / "sent.json")
    queue = _queue(tmp_path, max_items=2)

    class _Registry:
        def record_success(self, key):
            return None

    def article(index):
        return GlobalArticle(
            article_id=f"overflow-{index}",
            title=f"Headline {index}",
            content="본문",
            published_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        )

    first = SourceSpec(
        key="first",
        label="첫 소스",
        fetch=lambda: [article(0), article(1)],
        market="US",
    )
    second = SourceSpec(
        key="second",
        label="두 번째 소스",
        fetch=lambda: [article(2)],
        market="US",
    )

    async def run():
        await collect_report_source(first, _Registry(), tracker, queue, {})
        await collect_report_source(second, _Registry(), tracker, queue, {})

    asyncio.run(run())

    _, queued = asyncio.run(queue.snapshot())
    assert [row["article_id"] for row in queued] == ["overflow-1", "overflow-2"]
    assert "overflow-0" not in tracker._pending


def test_queue_clear_empties_the_file(tmp_path):
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0)]))

    asyncio.run(queue.clear())

    assert json.loads((tmp_path / "news_report_queue.json").read_text(encoding="utf-8"))["items"] == []


# ── 매시간 원문 수집 ──────────────────────────────────

def test_report_collection_reserves_and_queues_without_translating(tmp_path):
    """수집 주기는 LLM을 호출하지 않고 원문만 큐에 저장한다."""
    articles = [
        GlobalArticle(
            article_id=f"a-{index}",
            title=f"Fed holds rates {index}",
            content="본문",
            published_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        )
        for index in range(3)
    ]
    spec = SourceSpec(key="gnews_us", label="구글뉴스", fetch=lambda: articles, market="US")

    class _Registry:
        def record_success(self, key):
            self.ok = key

        def record_failure(self, key, reason):
            raise AssertionError("소스가 실패하지 않았다")

    tracker = _RecordingTracker()
    queue = _queue(tmp_path)

    count = asyncio.run(
        collect_report_source(spec, _Registry(), tracker, queue, {}, None, "cycle-0")
    )

    assert count == 3
    assert sorted(tracker.reserved) == ["a-0", "a-1", "a-2"]
    assert tracker.released == []
    _, items = asyncio.run(queue.snapshot())
    assert {row["market"] for row in items} == {"US"}


def test_report_collection_releases_articles_the_queue_did_not_take(tmp_path):
    """큐가 받지 않은 기사는 예약을 해제해 다음 주기에 다시 볼 수 있게 한다."""
    article = GlobalArticle(
        article_id="a-0",
        title="Fed holds rates",
        content="본문",
        published_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
    )
    spec = SourceSpec(key="gnews_us", label="구글뉴스", fetch=lambda: [article], market="US")

    class _Registry:
        def record_success(self, key):
            return None

    tracker = _RecordingTracker()
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([{**_item(0), "article_id": "a-0", "event_id": ""}]))

    count = asyncio.run(
        collect_report_source(spec, _Registry(), tracker, queue, {}, None, "cycle-0")
    )

    assert count == 0
    assert tracker.released == ["a-0"]


# ── 요약 파싱 ─────────────────────────────────────────

def test_analyzer_returns_analysis_and_highlights(tmp_path):
    analyzer = _analyzer(tmp_path, _payload())

    result = analyzer.analyze("US", "00:00~03:00 UTC +9", [{"index": 0, "title": "t"}])

    assert result["analysis"] == "현재 시장상황 요약이다."
    assert result["highlights"][0]["title"] == "한국어 제목 0"


def test_analyzer_rejects_an_index_that_was_not_sent(tmp_path):
    """없는 index를 받아들이면 엉뚱한 기사에 감성이 붙는다."""
    analyzer = _analyzer(tmp_path, _payload(indexes=(7,)))

    with pytest.raises(NewsReportError):
        analyzer.analyze("US", "창", [{"index": 0, "title": "t"}])


def test_analyzer_rejects_a_repeated_index(tmp_path):
    analyzer = _analyzer(tmp_path, _payload(indexes=(0, 0)))

    with pytest.raises(NewsReportError):
        analyzer.analyze("US", "창", [{"index": 0, "title": "t"}])


def test_analyzer_caps_highlights_at_the_configured_limit(tmp_path):
    analyzer = _analyzer(tmp_path, _payload(indexes=(0, 1, 2)), max_highlights=2)

    result = analyzer.analyze(
        "US", "창", [{"index": index, "title": "t"} for index in range(3)]
    )

    assert len(result["highlights"]) == 2


# ── 시장 분류와 섹션 ──────────────────────────────────

def test_markets_are_grouped_in_display_order():
    grouped = group_by_market([_item(0, market="KR"), _item(1, market="CN")])

    assert [market for market, _ in grouped] == ["CN", "KR"]


def test_failed_market_still_shows_its_headlines():
    """분석이 실패해도 그 시장의 수집 뉴스를 통째로 잃지 않는다."""
    section = format_market_section("US", [_item(0)], None)

    assert "요약 생성 실패" in section
    assert "Headline 0" in section


# ── 전송 ──────────────────────────────────────────────

def _send_app(tmp_path, *, bot=None, analyzer=None):
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0), _item(1)]))
    tracker = _RecordingTracker()
    news_log, prediction_log = _RecordingLog(), _RecordingLog()
    app = _App(
        bot=bot or _RecordingBot(),
        news_report_queue=queue,
        news_report_analyzer=analyzer or _analyzer(tmp_path, _payload()),
        sent_tracker=tracker,
        news_log=news_log,
        prediction_log=prediction_log,
    )
    return app, queue, tracker, news_log, prediction_log


def test_report_sends_confirms_and_clears_the_queue(tmp_path):
    app, queue, tracker, news_log, prediction_log = _send_app(tmp_path)

    asyncio.run(send_news_report(app))

    assert "3시간 시장상황 보고서" in app.bot.messages[0]
    assert "UTC +9" in app.bot.messages[0]
    assert "JST" not in app.bot.messages[0]
    assert "한국어 제목 0" in app.bot.messages[0]
    # 큐에 있던 기사는 전부 확정된다 — release하면 주간 주기가 다시 번역한다.
    assert sorted(tracker.confirmed) == ["gnews_us-0", "gnews_us-1"]
    assert asyncio.run(queue.snapshot())[1] == []
    # 주요 기사는 주간 번역과 같은 로그로 들어간다.
    assert len(news_log.records) == 1
    assert len(prediction_log.records) == 1


def test_report_keeps_the_queue_when_telegram_fails(tmp_path):
    app, queue, tracker, _, _ = _send_app(tmp_path, bot=_RecordingBot(fail=True))

    asyncio.run(send_news_report(app))

    assert tracker.confirmed == []
    assert len(asyncio.run(queue.snapshot())[1]) == 2


@pytest.mark.xfail(
    strict=True,
    reason="partial Telegram success currently confirms and clears every queued article",
)
def test_report_keeps_only_the_second_chunk_when_that_send_fails(tmp_path, monkeypatch):
    """부분 성공이면 성공한 chunk만 확정하고 실패한 chunk만 재시도해야 한다."""
    monkeypatch.setattr("news.report.NEWS_DIGEST_MESSAGE_MAX_CHARS", 240)
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0, market="CN")]))
    asyncio.run(queue.enqueue([_item(1, market="US")]))
    tracker = _RecordingTracker()
    bot = _FailOnCallBot(fail_on=2)
    app = _App(
        bot=bot,
        news_report_queue=queue,
        news_report_analyzer=_analyzer(tmp_path, _payload()),
        sent_tracker=tracker,
        news_log=_RecordingLog(),
        prediction_log=_RecordingLog(),
    )

    asyncio.run(send_news_report(app))

    _, remaining = asyncio.run(queue.snapshot())
    assert bot.calls == 2
    assert len(tracker.confirmed) == 1
    assert len(remaining) == 1
    assert remaining[0]["article_id"] not in tracker.confirmed


@pytest.mark.xfail(
    strict=True,
    reason="report highlights are logged before Telegram delivery succeeds",
)
def test_repeated_total_send_failure_does_not_duplicate_prediction_log(tmp_path):
    """전송되지 않은 신호는 재시도 횟수만큼 append되면 안 된다."""
    app, queue, tracker, news_log, prediction_log = _send_app(
        tmp_path,
        bot=_RecordingBot(fail=True),
    )

    asyncio.run(send_news_report(app))
    asyncio.run(send_news_report(app))

    assert tracker.confirmed == []
    assert len(asyncio.run(queue.snapshot())[1]) == 2
    assert prediction_log.records == []
    assert news_log.records == []


def test_report_uses_one_llm_call_per_market(tmp_path):
    """기사 수와 무관하게 보고서 한 번에 시장당 한 번만 호출한다."""
    analyzer = _analyzer(tmp_path, _payload())
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0, market="US"), _item(1, market="US")]))
    asyncio.run(queue.enqueue([_item(2, market="CN")]))
    app = _App(
        news_report_queue=queue,
        news_report_analyzer=analyzer,
        sent_tracker=_RecordingTracker(),
        news_log=None,
        prediction_log=None,
    )

    asyncio.run(send_news_report(app))

    assert len(analyzer._backend.calls) == 2


def test_report_survives_a_market_whose_summary_failed(tmp_path):
    app, queue, tracker, _, _ = _send_app(
        tmp_path, analyzer=_analyzer(tmp_path, error=RuntimeError("cloudflare down"))
    )

    asyncio.run(send_news_report(app))

    assert "요약 생성 실패" in app.bot.messages[0]
    assert sorted(tracker.confirmed) == ["gnews_us-0", "gnews_us-1"]


def test_empty_queue_sends_nothing(tmp_path):
    app = _App(
        news_report_queue=_queue(tmp_path),
        news_report_analyzer=_analyzer(tmp_path, _payload()),
        sent_tracker=_RecordingTracker(),
    )

    asyncio.run(send_news_report(app))

    assert app.bot.messages == []


def test_jobs_collect_hourly_and_report_every_three_hours_utc_plus_9():
    scheduler = _RecordingScheduler()

    news_feature._install_jobs(scheduler, object())

    jobs = {kwargs["id"]: kwargs for _, kwargs in scheduler.jobs}
    assert jobs["news_collection"]["trigger"] == "interval"
    assert jobs["news_collection"]["minutes"] == 60
    assert jobs["market_situation_report"]["trigger"] == "cron"
    assert jobs["market_situation_report"]["hour"] == "*/3"
    assert jobs["market_situation_report"]["minute"] == 0
    assert jobs["market_situation_report"]["timezone"] is JST


def test_report_prompt_requires_market_inference_instead_of_article_translation():
    prompt = _prompt_file().read_text(encoding="utf-8")

    assert "최근 3시간" in prompt
    assert "현재 시장상황" in prompt
    assert "다음 3시간" in prompt
    assert "UTC +9" in prompt
    assert "기사를 차례로 번역하거나 나열하지 않는다" in prompt
    assert "야간" not in prompt
