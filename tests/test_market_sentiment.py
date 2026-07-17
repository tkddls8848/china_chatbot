from datetime import datetime, timedelta
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from state.news_log import aggregate_market_sentiment, market_history_gaps


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

