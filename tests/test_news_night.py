"""야간 수집과 아침 야간 다이제스트."""

import asyncio
import json
from datetime import datetime

import pytest

from core.clock import KST
from llm.night_digest import NightDigestAnalyzer, NightDigestError
from news.night import (
    collect_night_source,
    format_market_section,
    group_by_market,
    is_night_window,
    send_night_digest,
)
from news.registry import SourceSpec
from news.sources import GlobalArticle
from state import NightNewsQueue


class _RecordingBot:
    def __init__(self, fail=False):
        self.messages = []
        self._fail = fail

    async def send_message(self, chat_id, text, parse_mode=None):
        if self._fail:
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


def _analyzer(tmp_path, payload=None, error=None, max_highlights=8):
    return NightDigestAnalyzer(
        backend=_FakeBackend(payload, error),
        prompt_file=_prompt_file(),
        num_predict=2048,
        max_highlights=max_highlights,
    )


def _prompt_file():
    from core.config import NEWS_NIGHT_DIGEST_PROMPT_FILE

    return NEWS_NIGHT_DIGEST_PROMPT_FILE


def _queue(tmp_path, per_source_limit=12, max_items=600):
    return NightNewsQueue(
        tmp_path / "night_queue.json",
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


def _payload(analysis="야간 흐름 요약이다.", indexes=(0,)):
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


# ── 야간 구간 판정 ────────────────────────────────────

def test_night_window_covers_the_configured_hours():
    assert is_night_window(datetime(2026, 8, 18, 3, 0, tzinfo=KST))
    assert is_night_window(datetime(2026, 8, 18, 0, 0, tzinfo=KST))
    # 종료 시각은 이미 주간이다. 그 주기가 야간 큐를 비운다.
    assert not is_night_window(datetime(2026, 8, 18, 7, 0, tzinfo=KST))
    assert not is_night_window(datetime(2026, 8, 18, 14, 0, tzinfo=KST))


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


def test_queue_clear_empties_the_file(tmp_path):
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0)]))

    asyncio.run(queue.clear())

    assert json.loads((tmp_path / "night_queue.json").read_text(encoding="utf-8"))["items"] == []


# ── 야간 수집 ─────────────────────────────────────────

def test_night_collection_reserves_and_queues_without_translating(tmp_path):
    """야간 주기는 LLM을 부르지 않는다. 부르면 밤새 210회가 된다."""
    articles = [
        GlobalArticle(
            article_id=f"a-{index}",
            title=f"Fed holds rates {index}",
            content="본문",
            published_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
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
        collect_night_source(spec, _Registry(), tracker, queue, {}, None, "cycle-0")
    )

    assert count == 3
    assert sorted(tracker.reserved) == ["a-0", "a-1", "a-2"]
    assert tracker.released == []
    _, items = asyncio.run(queue.snapshot())
    assert {row["market"] for row in items} == {"US"}


def test_night_collection_releases_articles_the_queue_did_not_take(tmp_path):
    """큐가 받지 않은 기사를 예약한 채 두면 아침에도 영영 보이지 않는다."""
    article = GlobalArticle(
        article_id="a-0",
        title="Fed holds rates",
        content="본문",
        published_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    )
    spec = SourceSpec(key="gnews_us", label="구글뉴스", fetch=lambda: [article], market="US")

    class _Registry:
        def record_success(self, key):
            return None

    tracker = _RecordingTracker()
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([{**_item(0), "article_id": "a-0", "event_id": ""}]))

    count = asyncio.run(
        collect_night_source(spec, _Registry(), tracker, queue, {}, None, "cycle-0")
    )

    assert count == 0
    assert tracker.released == ["a-0"]


# ── 요약 파싱 ─────────────────────────────────────────

def test_analyzer_returns_analysis_and_highlights(tmp_path):
    analyzer = _analyzer(tmp_path, _payload())

    result = analyzer.analyze("US", "00:00~07:00 KST", [{"index": 0, "title": "t"}])

    assert result["analysis"] == "야간 흐름 요약이다."
    assert result["highlights"][0]["title"] == "한국어 제목 0"


def test_analyzer_rejects_an_index_that_was_not_sent(tmp_path):
    """없는 index를 받아들이면 엉뚱한 기사에 감성이 붙는다."""
    analyzer = _analyzer(tmp_path, _payload(indexes=(7,)))

    with pytest.raises(NightDigestError):
        analyzer.analyze("US", "창", [{"index": 0, "title": "t"}])


def test_analyzer_rejects_a_repeated_index(tmp_path):
    analyzer = _analyzer(tmp_path, _payload(indexes=(0, 0)))

    with pytest.raises(NightDigestError):
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
    """요약이 실패해도 그 시장의 야간 뉴스를 통째로 잃지 않는다."""
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
        night_queue=queue,
        night_digest_analyzer=analyzer or _analyzer(tmp_path, _payload()),
        sent_tracker=tracker,
        news_log=news_log,
        prediction_log=prediction_log,
    )
    return app, queue, tracker, news_log, prediction_log


def test_digest_sends_confirms_and_clears_the_queue(tmp_path):
    app, queue, tracker, news_log, prediction_log = _send_app(tmp_path)

    asyncio.run(send_night_digest(app))

    assert "야간 뉴스 다이제스트" in app.bot.messages[0]
    assert "한국어 제목 0" in app.bot.messages[0]
    # 큐에 있던 기사는 전부 확정된다 — release하면 주간 주기가 다시 번역한다.
    assert sorted(tracker.confirmed) == ["gnews_us-0", "gnews_us-1"]
    assert asyncio.run(queue.snapshot())[1] == []
    # 주요 기사는 주간 번역과 같은 로그로 들어간다.
    assert len(news_log.records) == 1
    assert len(prediction_log.records) == 1


def test_digest_keeps_the_queue_when_telegram_fails(tmp_path):
    app, queue, tracker, _, _ = _send_app(tmp_path, bot=_RecordingBot(fail=True))

    asyncio.run(send_night_digest(app))

    assert tracker.confirmed == []
    assert len(asyncio.run(queue.snapshot())[1]) == 2


def test_digest_uses_one_llm_call_per_market(tmp_path):
    """기사별 번역이면 밤새 수백 회다. 야간에는 시장당 한 번만 부른다."""
    analyzer = _analyzer(tmp_path, _payload())
    queue = _queue(tmp_path)
    asyncio.run(queue.enqueue([_item(0, market="US"), _item(1, market="US")]))
    asyncio.run(queue.enqueue([_item(2, market="CN")]))
    app = _App(
        night_queue=queue,
        night_digest_analyzer=analyzer,
        sent_tracker=_RecordingTracker(),
        news_log=None,
        prediction_log=None,
    )

    asyncio.run(send_night_digest(app))

    assert len(analyzer._backend.calls) == 2


def test_digest_survives_a_market_whose_summary_failed(tmp_path):
    app, queue, tracker, _, _ = _send_app(
        tmp_path, analyzer=_analyzer(tmp_path, error=RuntimeError("cloudflare down"))
    )

    asyncio.run(send_night_digest(app))

    assert "요약 생성 실패" in app.bot.messages[0]
    assert sorted(tracker.confirmed) == ["gnews_us-0", "gnews_us-1"]


def test_empty_queue_sends_nothing(tmp_path):
    app = _App(
        night_queue=_queue(tmp_path),
        night_digest_analyzer=_analyzer(tmp_path, _payload()),
        sent_tracker=_RecordingTracker(),
    )

    asyncio.run(send_night_digest(app))

    assert app.bot.messages == []
