import asyncio
from datetime import datetime, timedelta, timezone

from core.config import NEWS_DIGEST_MESSAGE_MAX_CHARS, TELEGRAM_MESSAGE_LIMIT
from news.pipeline import (
    PreparedGlobalArticle,
    archive_unsent_articles,
    select_digest_rows,
    send_global_digest,
)
from news.sources import GlobalArticle
from news.utils import (
    chunk_message_items,
    compact_kst_time,
    filter_articles_for_kst_day,
    filter_recent_articles,
    format_china_time_as_kst,
    format_digest_article,
    truncate_text,
)


def test_truncate_text_remains_available_for_titles():
    result = truncate_text("가" * 150, 100)

    assert len(result) == 100
    assert result.endswith("...")


def test_truncate_text_keeps_short_text():
    assert truncate_text("짧은 기사 요약", 100) == "짧은 기사 요약"


def test_chunk_message_items_keeps_articles_whole_and_ordered():
    items = ["가" * 40, "나" * 40, "다" * 40]

    chunks = chunk_message_items(
        items,
        text_getter=lambda item: item,
        max_body_length=81,
        separator="\n",
    )

    assert chunks == [[items[0], items[1]], [items[2]]]
    assert [item for chunk in chunks for item in chunk] == items


class _RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.messages.append(text)


class _NoopTracker:
    async def confirm(self, article_id):
        return None

    async def release(self, article_id):
        return None


class _RecordingTracker:
    def __init__(self):
        self.confirmed = []
        self.released = []

    async def confirm(self, article_id):
        self.confirmed.append(article_id)

    async def release(self, article_id):
        self.released.append(article_id)


class _RecordingLog:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


def _row(index, *, impact="", sentiment=None, source_key="futu", article_chars=100):
    from news.registry import SourceSpec
    from llm.translator import TranslationResult

    spec = SourceSpec(key=source_key, label="푸투", fetch=lambda: [])
    return PreparedGlobalArticle(
        spec=spec,
        article=GlobalArticle(
            article_id=f"{source_key}-{index}",
            title="제목",
            content="본문",
            published_at="2026-08-01 10:00:00",
        ),
        text="가" * article_chars,
        translated=TranslationResult("제목", "본문", [], sentiment, impact),
    )


def _prepared_rows(count, *, article_chars, source_key="futu"):
    return [
        _row(index, source_key=source_key, article_chars=article_chars)
        for index in range(count)
    ]


def test_digest_splits_one_oversized_source_across_messages():
    """소스 하나의 기사가 한 메시지에 안 들어가면 나눠 보낸다.

    chunk_message_items는 아이템을 쪼개지 못하므로, 섹션을 미리 나누지 않으면
    텔레그램 4096자 제한에 걸려 그 소스의 다이제스트가 통째로 실패한다.
    """
    bot = _RecordingBot()
    # 한 소스에 큰 기사 6건 → 단일 섹션이면 상한을 크게 넘는다.
    rows = _prepared_rows(6, article_chars=900)

    asyncio.run(
        send_global_digest(bot, "chat", rows, _NoopTracker(), None, None)
    )

    assert len(bot.messages) > 1
    for message in bot.messages:
        assert len(message) <= TELEGRAM_MESSAGE_LIMIT, len(message)
        assert len(message) <= NEWS_DIGEST_MESSAGE_MAX_CHARS
    # 기사는 하나도 잃지 않고 모두 실려야 한다.
    assert sum(message.count("가" * 900) for message in bot.messages) == 6
    # 소스 수는 섹션 분할과 무관하게 1곳으로 센다.
    assert "소스 1곳 · 새 기사 6건" in bot.messages[0]


def test_digest_keeps_small_sources_in_one_message():
    bot = _RecordingBot()
    rows = _prepared_rows(2, article_chars=200, source_key="sina")

    asyncio.run(
        send_global_digest(bot, "chat", rows, _NoopTracker(), None, None)
    )

    assert len(bot.messages) == 1
    assert "소스 1곳 · 새 기사 2건 · 1/1" in bot.messages[0]


def test_selection_sends_only_the_highest_impact_articles():
    """번역은 6건, 송출은 impact 상위 3건이다."""
    rows = [
        _row(0, impact="low", sentiment=0.9),
        _row(1, impact="high", sentiment=0.1),
        _row(2, impact="medium", sentiment=0.2),
        _row(3, impact="high", sentiment=0.8),
        _row(4, impact="low", sentiment=-0.5),
        _row(5, impact="medium", sentiment=-0.9),
    ]

    selected, dropped = select_digest_rows(rows, 3)

    assert [row.article.article_id for row in selected] == [
        "futu-1",  # high
        "futu-3",  # high
        "futu-5",  # medium 중 감성이 가장 센 건
    ]
    assert [row.article.article_id for row in dropped] == [
        "futu-0",
        "futu-2",
        "futu-4",
    ]


def test_selection_breaks_impact_ties_by_sentiment_strength_then_recency():
    rows = [
        _row(0, impact="high", sentiment=0.2),
        _row(1, impact="high", sentiment=-0.7),  # 세기는 부호와 무관하다
        _row(2, impact="high", sentiment=0.2),  # 같은 세기면 뒤쪽(최신)이 이긴다
    ]

    selected, dropped = select_digest_rows(rows, 2)

    assert [row.article.article_id for row in selected] == ["futu-1", "futu-2"]
    assert [row.article.article_id for row in dropped] == ["futu-0"]


def test_selection_pushes_missing_impact_or_sentiment_to_the_back():
    rows = [
        _row(0, impact="", sentiment=0.9),  # impact 없음 → 제일 뒤
        _row(1, impact="low", sentiment=None),  # sentiment 없음 → low 안에서 뒤
        _row(2, impact="low", sentiment=0.1),
    ]

    selected, dropped = select_digest_rows(rows, 2)

    assert [row.article.article_id for row in selected] == ["futu-1", "futu-2"]
    assert [row.article.article_id for row in dropped] == ["futu-0"]
    # low 안에서는 sentiment가 있는 쪽이 먼저다.
    assert select_digest_rows(rows, 1)[0][0].article.article_id == "futu-2"


def test_selection_keeps_everything_when_under_the_limit():
    rows = [_row(0, impact="low"), _row(1, impact="high")]

    selected, dropped = select_digest_rows(rows, 3)

    assert selected == rows
    assert dropped == []


def test_unsent_articles_are_confirmed_and_logged_without_release():
    """탈락분을 release하면 다음 주기에 다시 번역한다 — 확정하고 로그만 남긴다."""
    tracker = _RecordingTracker()
    news_log, prediction_log = _RecordingLog(), _RecordingLog()
    dropped = [_row(0, impact="low", sentiment=0.3), _row(1, impact="low", sentiment=0.2)]

    asyncio.run(archive_unsent_articles(dropped, tracker, prediction_log, news_log))

    assert tracker.confirmed == ["futu-0", "futu-1"]
    assert tracker.released == []
    assert len(news_log.records) == 2
    assert len(prediction_log.records) == 2


def test_send_failure_releases_only_the_sent_group():
    """다이제스트 전송이 실패해도 탈락분은 영향받지 않는다."""

    class _FailingBot:
        async def send_message(self, chat_id, text, parse_mode=None):
            raise RuntimeError("telegram down")

    tracker = _RecordingTracker()
    news_log, prediction_log = _RecordingLog(), _RecordingLog()
    rows = [
        _row(0, impact="low", sentiment=0.1),
        _row(1, impact="high", sentiment=0.5),
        _row(2, impact="high", sentiment=0.4),
        _row(3, impact="low", sentiment=0.2),
    ]
    selected, dropped = select_digest_rows(rows, 2)

    async def run():
        await send_global_digest(
            _FailingBot(), "chat", selected, tracker, prediction_log, news_log
        )
        await archive_unsent_articles(dropped, tracker, prediction_log, news_log)

    asyncio.run(run())

    # 송출 대상만 예약이 풀려 다음 주기에 다시 시도된다.
    assert sorted(tracker.released) == ["futu-1", "futu-2"]
    # 탈락분은 전송 경로를 타지 않았으므로 그대로 확정·기록된다.
    assert sorted(tracker.confirmed) == ["futu-0", "futu-3"]
    assert len(news_log.records) == 2


def test_long_summary_article_still_fits_one_digest_message():
    """요약이 400자로 길어져도 기사 하나가 메시지 상한을 넘지 않는다."""
    text = format_digest_article(
        "제" * 130,  # 제목은 120자로 잘린다
        "본" * 450,  # 400자 내외 지시의 상단
        "09:15:00 KST",
        "- 감성 : 긍정 +0.50 · 영향 높음",
        url="https://example.com/news?" + "a" * 470,
    )
    bot = _RecordingBot()
    rows = [
        PreparedGlobalArticle(
            spec=row.spec, article=row.article, text=text, translated=row.translated
        )
        for row in _prepared_rows(3, article_chars=1)
    ]

    asyncio.run(send_global_digest(bot, "chat", rows, _NoopTracker(), None, None))

    assert sum(message.count(text) for message in bot.messages) == 3
    for message in bot.messages:
        assert len(message) <= NEWS_DIGEST_MESSAGE_MAX_CHARS, len(message)


def test_china_article_timestamp_includes_date_and_time_in_kst():
    assert (
        format_china_time_as_kst("23:30:00", "2026-07-18")
        == "2026-07-19 00:30:00 KST"
    )


def test_rss_article_timestamp_respects_source_timezone():
    assert (
        format_china_time_as_kst("Fri, 17 Jul 2026 14:30:00 GMT")
        == "2026-07-17 23:30:00 KST"
    )


def test_recent_article_filter_drops_stale_unknown_and_future_items():
    now = datetime(2026, 7, 19, 12, tzinfo=timezone(timedelta(hours=9)))
    recent = GlobalArticle("recent", "recent", "", "Sun, 19 Jul 2026 01:00:00 GMT")
    stale = GlobalArticle("stale", "stale", "", "Fri, 19 Jun 2026 01:00:00 GMT")
    unknown = GlobalArticle("unknown", "unknown", "", "")
    future = GlobalArticle("future", "future", "", "Mon, 20 Jul 2026 12:00:00 GMT")

    assert filter_recent_articles(
        [stale, unknown, recent, future],
        max_age_hours=48,
        now=now,
    ) == [recent]


def test_calendar_day_filter_uses_kst_date_and_sorts_newest_first():
    early = GlobalArticle("early", "early", "", "Fri, 03 Jul 2026 15:30:00 GMT")
    late = GlobalArticle("late", "late", "", "Sat, 04 Jul 2026 10:00:00 GMT")
    previous = GlobalArticle("previous", "previous", "", "Fri, 03 Jul 2026 14:59:00 GMT")

    assert filter_articles_for_kst_day(
        [early, previous, late],
        datetime(2026, 7, 4).date(),
    ) == [late, early]


def test_article_display_keeps_only_kst_time():
    assert compact_kst_time("2026-07-19 09:15:00 KST") == "09:15:00 KST"
    assert compact_kst_time("2026-07-19 09:15 KST") == "09:15 KST"


def test_digest_article_uses_text_file_layout():
    assert format_digest_article(
        "기사 제목",
        "기사 본문",
        "09:15:00 KST",
        "- 감성 : 긍정 +0.50 · 영향 높음",
    ) == (
        "• 기사 제목 (09:15:00 KST)\n"
        "- 기사 본문\n"
        "- 감성 : 긍정 +0.50 · 영향 높음"
    )


def test_digest_article_keeps_original_link_on_title():
    assert format_digest_article(
        "기사 제목",
        "기사 본문",
        "2026-07-19 09:15 KST",
        url="https://example.com/news?a=1&b=2",
    ).startswith(
        '• <a href="https://example.com/news?a=1&amp;b=2">기사 제목</a> '
    )
