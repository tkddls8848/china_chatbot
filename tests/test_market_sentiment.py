import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from state.news_log import NewsLog, aggregate_market_sentiment, market_history_gaps
from features.market_sentiment import handlers as commands
from features.market_sentiment.chart import _trend_series
from news.backfill import _article_time
from news.sources import GlobalArticle


def test_aggregate_market_sentiment_groups_article_once_per_market():
    now = datetime.now()
    entries = [
        {"ts": now.isoformat(), "sentiment": 0.8, "market": "us", "codes": ["A", "B"]},
        {"ts": now.isoformat(), "sentiment": -0.2, "market": "US", "codes": []},
        {"ts": now.isoformat(), "sentiment": -0.6, "market": "KR", "codes": []},
        {"ts": (now - timedelta(hours=49)).isoformat(), "sentiment": 1.0, "market": "US", "codes": []},
        {"ts": now.isoformat(), "sentiment": None, "market": "US", "codes": []},
    ]

    result = aggregate_market_sentiment(entries, since_hours=48)

    assert result["US"]["count"] == 2
    assert result["US"]["avg_sentiment"] == pytest.approx(0.3)
    assert result["KR"]["avg_sentiment"] == -0.6
    assert len(result["US"]["daily"]) == 1


def test_market_history_gaps_rejects_thin_series():
    markets = {
        "US": {"count": 6, "daily": [{}, {}, {}]},
        "KR": {"count": 1, "daily": [{}]},
    }

    gaps = market_history_gaps(markets, {"US", "KR"}, minimum_articles=6, minimum_days=3)

    assert gaps == {"KR": "1/6 scored articles"}


def test_trend_series_uses_sorted_real_dates():
    dates, values = _trend_series(
        [
            {"date": "2026-07-18", "avg_sentiment": 0.1},
            {"date": "2026-07-11", "avg_sentiment": -0.2},
            {"date": "2026-07-15", "avg_sentiment": 0.4},
        ]
    )

    assert [day.date().isoformat() for day in dates] == [
        "2026-07-11",
        "2026-07-15",
        "2026-07-18",
    ]
    assert values == [-0.2, 0.4, 0.1]


def test_history_coverage_extends_beyond_existing_seven_days(tmp_path):
    today = datetime.now().date()
    rows = []
    for market in ("CN", "HK", "US", "KR"):
        for offset in range(1, 8):
            day = today - timedelta(days=offset)
            rows.append(
                    {
                        "ts": datetime.now().isoformat(),
                        "timestamp_source": "published",
                    "source": f"history:{market}",
                    "article_id": (
                        f"history:{market}:rss:history:{market}:"
                        f"{day.isoformat()}:article-{offset}"
                    ),
                    "sentiment": 0.1,
                    "market": market,
                }
            )
    path = tmp_path / "news_log.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    news_log = NewsLog(path, retention_days=30)

    missing = asyncio.run(
        news_log.missing_history_days({"CN", "HK", "US", "KR"}, 14)
    )

    expected = [
        today - timedelta(days=offset)
        for offset in (0, *range(8, 14))
    ]
    assert all(days == expected for days in missing.values())


def test_history_timestamp_uses_requested_calendar_day():
    target = date(2026, 7, 4)
    article = GlobalArticle(
        article_id="test",
        title="title",
        content="content",
        published_at="Fri, 03 Jul 2026 15:30:00 GMT",
    )

    assert _article_time(article, target) == datetime(2026, 7, 4, 0, 30)


def test_history_timestamp_rejects_article_from_another_kst_day():
    article = GlobalArticle(
        article_id="test",
        title="title",
        content="content",
        published_at="Fri, 17 Jul 2026 14:30:00 GMT",
    )

    assert _article_time(article, date(2026, 7, 4)) is None


def test_calendar_snapshot_uses_only_verified_publication_times(tmp_path):
    log = NewsLog(tmp_path / "news_log.json", retention_days=30)
    published_at = datetime.now().replace(microsecond=0)

    async def exercise():
        await log.record(
            source="gnews",
            title="verified",
            sentiment=0.2,
            impact="low",
            codes=[],
            market="US",
            article_id="verified",
            occurred_at=published_at,
        )
        await log.record(
            source="gnews",
            title="collection time only",
            sentiment=0.2,
            impact="low",
            codes=[],
            market="US",
            article_id="unverified",
        )
        return await log.snapshot_since_date(published_at.date())

    rows = asyncio.run(exercise())

    assert [row["article_id"] for row in rows] == ["verified"]
    assert rows[0]["ts"] == published_at.isoformat(timespec="seconds")


def test_news_log_discards_legacy_inaccurate_timestamps(tmp_path):
    path = tmp_path / "news_log.json"
    path.write_text(
        json.dumps(
            [
                {
                    "ts": datetime.now().isoformat(),
                    "source": "gnews",
                    "article_id": "legacy",
                    "sentiment": 0.2,
                    "market": "US",
                }
            ]
        ),
        encoding="utf-8",
    )

    NewsLog(path, retention_days=30)

    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_backfill_day_limit_spreads_across_full_window():
    days = [
        date(2026, 7, 17) - timedelta(days=offset)
        for offset in range(23)
    ]

    selected = commands._spread_backfill_days(days, 7)

    assert len(selected) == 7
    assert selected[0] == days[0]
    assert selected[-1] == days[-1]
    assert len(set(selected)) == 7


def test_market_command_backfills_longer_window_even_when_chart_is_ready(monkeypatch):
    target_day = datetime.now().date() - timedelta(days=8)
    backfill_calls = []

    class NewsLogStub:
        async def snapshot_since_date(self, start_date):
            assert start_date == datetime.now().date() - timedelta(days=13)
            return []

        async def missing_history_days(self, markets, lookback_days):
            assert lookback_days == 14
            return {
                market: ([target_day] if market == "US" else [])
                for market in markets
            }

    class Status:
        async def edit_text(self, text):
            self.text = text

        async def delete(self):
            self.deleted = True

    class Message:
        async def reply_text(self, text):
            return Status()

        async def reply_photo(self, **kwargs):
            self.photo = kwargs

    ready = {
        "CN": {
            "avg_sentiment": 0.1,
            "count": 6,
            "daily": [{"date": "2026-07-18", "avg_sentiment": 0.1}],
        },
        "US": {
            "avg_sentiment": 0.2,
            "count": 6,
            "daily": [{"date": "2026-07-18", "avg_sentiment": 0.2}],
        },
    }

    async def fake_backfill(*args, **kwargs):
        backfill_calls.append(
            {
                "markets": args[3],
                "days": kwargs["days_by_market"],
            }
        )
        return {"US": 1}

    async def fake_run_non_urgent(func, *args):
        return b"chart"

    monkeypatch.setattr(commands, "aggregate_market_sentiment", lambda *args, **kwargs: ready)
    monkeypatch.setattr(commands, "market_history_gaps", lambda *args, **kwargs: {})
    monkeypatch.setattr(commands, "backfill_market_history", fake_backfill)
    monkeypatch.setattr(commands, "run_non_urgent", fake_run_non_urgent)

    message = Message()
    update = SimpleNamespace(effective_message=message, callback_query=None)
    context = SimpleNamespace(
        args=["14"],
        bot_data={
            "news_log": NewsLogStub(),
            "translator": object(),
            "translate_semaphore": object(),
        },
    )

    asyncio.run(commands.cmd_market(update, context))

    assert len(backfill_calls) == 1
    assert backfill_calls[0]["markets"] == {"US"}
    assert backfill_calls[0]["days"]["US"] == [target_day]
    assert message.photo["caption"].startswith("국가·증시별 뉴스 감성 — 최근 14일")


def test_thirty_day_backfill_targets_all_markets_and_full_range(monkeypatch):
    today = datetime.now().date()
    missing = [
        today - timedelta(days=offset)
        for offset in range(8, 31)
    ]
    captured = {}

    class NewsLogStub:
        async def snapshot_since_date(self, start_date):
            assert start_date == datetime.now().date() - timedelta(days=29)
            return []

        async def missing_history_days(self, markets, lookback_days):
            assert lookback_days == 30
            return {market: list(missing) for market in markets}

    class Status:
        async def edit_text(self, text):
            pass

        async def delete(self):
            pass

    class Message:
        async def reply_text(self, text):
            return Status()

        async def reply_photo(self, **kwargs):
            self.caption = kwargs["caption"]

    ready = {
        market: {
            "avg_sentiment": 0.1,
            "count": 6,
            "daily": [{"date": today.isoformat(), "avg_sentiment": 0.1}],
        }
        for market in ("CN", "HK", "US", "KR")
    }

    async def fake_backfill(*args, **kwargs):
        captured["markets"] = args[3]
        captured["days"] = kwargs["days_by_market"]
        return {market: 7 for market in args[3]}

    async def fake_run_non_urgent(func, *args):
        return b"chart"

    monkeypatch.setattr(commands, "aggregate_market_sentiment", lambda *args, **kwargs: ready)
    monkeypatch.setattr(commands, "market_history_gaps", lambda *args, **kwargs: {})
    monkeypatch.setattr(commands, "backfill_market_history", fake_backfill)
    monkeypatch.setattr(commands, "run_non_urgent", fake_run_non_urgent)

    message = Message()
    update = SimpleNamespace(effective_message=message, callback_query=None)
    context = SimpleNamespace(
        args=["30"],
        bot_data={
            "news_log": NewsLogStub(),
            "translator": object(),
            "translate_semaphore": object(),
        },
    )

    asyncio.run(commands.cmd_market(update, context))

    assert captured["markets"] == {"CN", "HK", "US", "KR"}
    assert all(len(days) == 7 for days in captured["days"].values())
    assert all(days[0] == missing[0] for days in captured["days"].values())
    assert all(days[-1] == missing[-1] for days in captured["days"].values())
    assert message.caption.startswith("국가·증시별 뉴스 감성 — 최근 30일")
