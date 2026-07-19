from datetime import datetime, timedelta, timezone

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
