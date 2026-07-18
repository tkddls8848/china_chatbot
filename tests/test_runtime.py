import asyncio
import itertools
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from bot import _acquire_single_instance_lock
from core import workers
from llm.market_view import MarketViewAnalyzer, MarketViewError


def test_second_instance_returns_none_instead_of_raising(tmp_path):
    first = _acquire_single_instance_lock(tmp_path / "bot.lock")
    assert first is not None
    try:
        assert _acquire_single_instance_lock(tmp_path / "bot.lock") is None
    finally:
        first.close()


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
