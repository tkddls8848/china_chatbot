import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from llm.market_view import MarketViewAnalyzer
from research import handlers


class _StockDatabaseStub:
    def get_display_name(self, code: str) -> str | None:
        return None


def test_low_relevance_watchlist_item_becomes_remove_candidate(monkeypatch):
    monkeypatch.setattr(handlers, "RESEARCH_REMOVE_RELEVANCE_THRESHOLD", 0.35)
    result = {
        "actions": [
            {
                "ticker": "600001",
                "name": "기존 종목",
                "action": "keep",
                "confidence": 0.8,
                "relevance": 0.2,
                "reason": "현재 마켓 뷰와 공급망 연관성이 낮음",
            }
        ]
    }

    actions = handlers._collect_research_actions(
        result,
        {"600001": "기존 종목"},
        _StockDatabaseStub(),
    )

    assert actions["add"] == []
    assert actions["remove"][0]["code"] == "600001"
    assert actions["remove"][0]["relevance"] == 0.2
    assert "삭제 기준 35% 미만" in actions["remove"][0]["reason"]


def test_high_relevance_watchlist_item_is_not_remove_candidate(monkeypatch):
    monkeypatch.setattr(handlers, "RESEARCH_REMOVE_RELEVANCE_THRESHOLD", 0.35)
    result = {
        "actions": [
            {
                "ticker": "600001",
                "action": "keep",
                "confidence": 0.8,
                "relevance": 0.7,
            }
        ]
    }

    actions = handlers._collect_research_actions(
        result,
        {"600001": "기존 종목"},
        _StockDatabaseStub(),
    )

    assert actions == {"add": [], "remove": []}


def test_explicit_remove_remains_compatible_without_relevance():
    result = {
        "actions": [
            {
                "ticker": "600001",
                "action": "remove",
                "confidence": 0.9,
                "reason": "제외 필요",
            }
        ]
    }

    actions = handlers._collect_research_actions(
        result,
        {"600001": "기존 종목"},
        _StockDatabaseStub(),
    )

    assert actions["remove"][0]["code"] == "600001"
    assert actions["remove"][0]["relevance"] is None


def test_market_view_parser_normalizes_relevance():
    analyzer = object.__new__(MarketViewAnalyzer)
    result = analyzer._parse_analysis(
        json.dumps(
            {
                "summary": "요약",
                "actions": [
                    {
                        "ticker": "600001",
                        "name": "종목",
                        "action": "remove",
                        "confidence": 0.8,
                        "relevance": -0.1,
                        "evidence": [],
                    }
                ],
                "risks": [],
            },
            ensure_ascii=False,
        )
    )

    assert result["actions"][0]["relevance"] == 0.0


class _WatchlistManagerStub:
    def __init__(self):
        self.items = {"600001": "삭제 종목", "600002": "유지 종목"}

    async def get_all(self):
        return self.items.copy()

    async def remove(self, code):
        return self.items.pop(code, None)

    async def add(self, code, name):
        self.items[code] = name


class _MessageStub:
    def __init__(self):
        self.text = ""

    async def edit_text(self, text, **kwargs):
        self.text = text


def test_apply_removes_approved_candidate():
    manager = _WatchlistManagerStub()
    message = _MessageStub()
    query = SimpleNamespace(message=message)
    context = SimpleNamespace(
        bot_data={
            "watchlist_manager": manager,
            "research_pending": {
                "request1": {
                    "add": [],
                    "remove": [{"code": "600001", "name": "삭제 종목"}],
                }
            },
        }
    )

    asyncio.run(handlers._handle_research_apply(query, context, "request1"))

    assert manager.items == {"600002": "유지 종목"}
    assert "삭제 종목 (600001)" in message.text
