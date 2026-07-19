import asyncio
import itertools
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

import bot
from bot import _acquire_single_instance_lock
from core import workers
from llm.market_view import MarketViewAnalyzer, MarketViewError, MarketViewManager
from watchlist.manager import WatchlistManager


def test_second_instance_returns_none_instead_of_raising(tmp_path):
    first = _acquire_single_instance_lock(tmp_path / "bot.lock")
    assert first is not None
    try:
        assert _acquire_single_instance_lock(tmp_path / "bot.lock") is None
    finally:
        first.close()


def test_new_watchlist_starts_empty(tmp_path):
    state_file = tmp_path / "watchlist.json"

    manager = WatchlistManager(state_file)

    assert asyncio.run(manager.get_all()) == {}
    assert json.loads(state_file.read_text(encoding="utf-8")) == {}


def test_scheduler_uses_application_lifecycle(monkeypatch):
    menu_configured = False

    async def configure_menu(_app):
        nonlocal menu_configured
        menu_configured = True

    monkeypatch.setattr(bot, "configure_telegram_menu", configure_menu)

    async def exercise():
        scheduler = AsyncIOScheduler()
        app = SimpleNamespace(bot_data={"scheduler": scheduler})

        await bot._start_application(app)
        assert menu_configured
        assert scheduler.running

        await bot._stop_scheduler(app)
        assert not scheduler.running

        # The shutdown hook is registered for both stop and shutdown phases.
        await bot._stop_scheduler(app)

    asyncio.run(exercise())


def test_non_urgent_workers_are_selected_round_robin(monkeypatch):
    monkeypatch.setattr(
        workers,
        "_NON_URGENT_EXECUTOR_SEQUENCE",
        itertools.count(),
    )

    async def collect_thread_names():
        return [
            await workers.run_non_urgent(lambda: threading.current_thread().name)
            for _ in range(len(workers._NON_URGENT_EXECUTORS) * 2)
        ]

    names = asyncio.run(collect_thread_names())
    expected = [
        f"non-urgent-{index + 1}_0"
        for index in range(len(workers._NON_URGENT_EXECUTORS))
    ] * 2
    assert names == expected


def _analyzer_with_timeout(seconds: int) -> MarketViewAnalyzer:
    analyzer = object.__new__(MarketViewAnalyzer)
    analyzer._timeout = seconds
    return analyzer


def test_remaining_timeout_uses_shared_research_budget(monkeypatch):
    analyzer = _analyzer_with_timeout(300)
    monkeypatch.setattr("llm.market_view.time.monotonic", lambda: 120.0)
    assert analyzer._remaining_timeout(300.0) == 180.0


def test_remaining_timeout_rejects_expired_budget(monkeypatch):
    analyzer = _analyzer_with_timeout(300)
    monkeypatch.setattr("llm.market_view.time.monotonic", lambda: 301.0)
    with pytest.raises(MarketViewError, match="timed out"):
        analyzer._remaining_timeout(300.0)


def test_analysis_request_uses_bounded_context_and_output(monkeypatch):
    analyzer = object.__new__(MarketViewAnalyzer)
    analyzer._base_url = "http://localhost:11434"
    analyzer._model = "model"
    analyzer._prompt = "prompt"
    analyzer._num_predict = 1024
    analyzer._num_ctx = 16384
    analyzer._num_thread = 6
    analyzer._num_gpu = 0
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"summary":"ok"}'}}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("llm.market_view.requests.post", post)
    analyzer._request_analysis({"market_view": "AI"})

    options = captured["json"]["options"]
    assert options["num_predict"] == 1024
    assert options["num_ctx"] == 16384
    assert options["num_thread"] == 6


def test_analysis_payload_includes_new_action_cap():
    analyzer = object.__new__(MarketViewAnalyzer)
    analyzer._enabled = True
    analyzer._timeout = 60
    analyzer._remove_relevance_threshold = 0.35
    analyzer._max_new_actions = 4
    analyzer._verification_enabled = False
    captured = {}

    def request(payload, **kwargs):
        captured.update(payload)
        return '{"summary":"요약","actions":[],"risks":[]}'

    analyzer._request_analysis = request
    analyzer.analyze("AI", {}, [], [])
    assert captured["max_new_actions"] == 4


def test_market_view_history_is_migrated_and_saved_as_compact_summaries(tmp_path):
    state_file = tmp_path / "market_research.json"
    legacy_results = [
        {
            "generated_at": f"2026-07-1{index}T10:00:00",
            "summary": str(index) * 400,
            "actions": [
                {"ticker": "AAPL", "action": "add", "reason": "긴 근거"},
                {"ticker": "TSLA", "action": "keep", "reason": "긴 근거"},
            ],
            "risks": ["전체 결과에만 필요한 필드"],
        }
        for index in range(3)
    ]
    state_file.write_text(
        json.dumps(
            {
                "sight": "AI",
                "updated_at": "2026-07-19T10:00:00",
                "last_result": legacy_results[-1],
                "history": legacy_results,
            }
        ),
        encoding="utf-8",
    )

    manager = MarketViewManager(state_file, history_limit=2)
    history = manager.get_history_summaries()
    persisted = json.loads(state_file.read_text(encoding="utf-8"))

    assert len(history) == 2
    assert len(history[0]["summary"]) == 300
    assert history[0]["actions"] == [{"ticker": "AAPL", "action": "add"}]
    assert set(persisted["history"][0]) == {"generated_at", "summary", "actions"}
    assert "last_result" not in persisted
    assert "risks" not in persisted["history"][0]
    assert manager.get_last_result() == history[-1]


def test_market_view_change_and_clear_remove_previous_analysis_context(tmp_path):
    state_file = tmp_path / "market_research.json"
    manager = MarketViewManager(state_file, history_limit=3)
    manager.set_sight("AI")
    manager.save_result(
        {
            "generated_at": "2026-07-19T10:00:00",
            "summary": "분석",
            "actions": [{"ticker": "AAPL", "action": "add"}],
            "risks": [],
        }
    )

    manager.set_sight("반도체")
    assert manager.get_last_result() is None
    assert manager.get_history_summaries() == []

    manager.save_result(
        {
            "generated_at": "2026-07-19T11:00:00",
            "summary": "새 분석",
            "actions": [],
            "risks": [],
        }
    )
    manager.clear_sight()
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted == {
        "sight": None,
        "updated_at": None,
        "history": [],
    }
