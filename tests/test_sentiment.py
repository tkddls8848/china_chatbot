import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from llm.translator import TranslationService
from news.utils import format_sentiment_line, normalize_stock_code
from state.news_log import aggregate_sentiment_by_code


def _parse(payload: dict):
    service = object.__new__(TranslationService)
    return service._parse_translation(json.dumps(payload, ensure_ascii=False))


def test_parse_translation_reads_sentiment_and_impact():
    result = _parse(
        {
            "title": "제목",
            "content": "본문",
            "mentioned_stocks": ["600519"],
            "sentiment": 0.6,
            "impact": "HIGH",
        }
    )
    assert result.sentiment == 0.6
    assert result.impact == "high"


def test_parse_translation_tolerates_missing_or_invalid_sentiment():
    result = _parse({"title": "제목", "content": "본문", "mentioned_stocks": []})
    assert result.sentiment is None
    assert result.impact == ""

    result = _parse(
        {
            "title": "제목",
            "content": "본문",
            "mentioned_stocks": [],
            "sentiment": "매우긍정",
            "impact": "엄청남",
        }
    )
    assert result.sentiment is None
    assert result.impact == ""


def test_sentiment_clamped_to_range():
    result = _parse(
        {"title": "제목", "content": "본문", "mentioned_stocks": [], "sentiment": -3}
    )
    assert result.sentiment == -1.0


def test_format_sentiment_line_markers():
    assert "🟢" in format_sentiment_line(0.5)
    assert "🔴" in format_sentiment_line(-0.5, "high")
    assert "높음" in format_sentiment_line(-0.5, "high")
    assert "⚪" in format_sentiment_line(0.0)
    assert format_sentiment_line(None) == ""


def test_normalize_stock_code():
    assert normalize_stock_code("700") == "00700"
    assert normalize_stock_code("600519") == "600519"
    assert normalize_stock_code("SZ000665") == "000665"
    assert normalize_stock_code("") == ""


def test_aggregate_sentiment_by_code():
    watchlist = {"600519": "귀주모태주", "09988": "알리바바"}
    entries = [
        {"ts": "2026-07-05T10:00:00", "title": "a", "sentiment": 0.5, "codes": ["600519"]},
        {"ts": "2026-07-05T11:00:00", "title": "b", "sentiment": -0.5, "codes": ["600519"]},
        {"ts": "2026-07-05T12:00:00", "title": "c", "sentiment": None, "codes": ["600519"]},
        {"ts": "2026-07-05T13:00:00", "title": "d", "sentiment": 0.9, "codes": ["999999"]},
    ]
    stats = aggregate_sentiment_by_code(entries, watchlist)
    assert stats["600519"]["count"] == 3
    assert stats["600519"]["avg_sentiment"] == 0.0
    assert "999999" not in stats
