import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from llm.market_view import MarketViewAnalyzer, MarketViewManager


def _manager(tmp_path, history_limit=3) -> MarketViewManager:
    return MarketViewManager(tmp_path / "state.json", history_limit=history_limit)


def _result(summary: str, actions=None) -> dict:
    return {"generated_at": "2026-07-05T10:00:00", "summary": summary, "actions": actions or [], "risks": []}


def test_history_capped_at_limit(tmp_path):
    manager = _manager(tmp_path, history_limit=2)
    for i in range(4):
        manager.save_result(_result(f"요약{i}"))
    summaries = manager.get_history_summaries()
    assert [s["summary"] for s in summaries] == ["요약2", "요약3"]


def test_history_summaries_only_include_add_remove(tmp_path):
    manager = _manager(tmp_path)
    manager.save_result(
        _result(
            "요약",
            [
                {"ticker": "600519", "action": "add"},
                {"ticker": "09988", "action": "keep"},
                {"ticker": "000001", "action": "remove"},
            ],
        )
    )
    actions = manager.get_history_summaries()[0]["actions"]
    assert actions == [
        {"ticker": "600519", "action": "add"},
        {"ticker": "000001", "action": "remove"},
    ]


def test_history_survives_reload(tmp_path):
    manager = _manager(tmp_path)
    manager.save_result(_result("요약"))
    reloaded = _manager(tmp_path)
    assert len(reloaded.get_history_summaries()) == 1


def _analyzer(verification_response: str) -> MarketViewAnalyzer:
    analyzer = object.__new__(MarketViewAnalyzer)
    analyzer._verification_enabled = True
    analyzer._verification_prompt = "verify"
    analyzer._request_analysis = lambda payload, prompt=None: verification_response
    return analyzer


def test_verify_actions_drops_and_annotates():
    analyzer = _analyzer(
        json.dumps(
            {
                "verdicts": [
                    {
                        "ticker": "600519",
                        "verdict": "keep",
                        "confidence": 0.8,
                        "bull_case": "정책 수혜",
                        "bear_case": "밸류에이션 부담",
                    },
                    {
                        "ticker": "000001",
                        "verdict": "drop",
                        "confidence": 0.7,
                        "bear_case": "근거 뉴스가 단일 기사뿐",
                    },
                ]
            },
            ensure_ascii=False,
        )
    )
    result = {
        "summary": "요약",
        "actions": [
            {"ticker": "600519", "action": "add", "name": "귀주모태주"},
            {"ticker": "000001", "action": "add", "name": "평안은행"},
            {"ticker": "09988", "action": "keep", "name": "알리바바"},
        ],
        "risks": [],
    }

    verified = analyzer._verify_actions("시장뷰", result, [], None)

    tickers = [a["ticker"] for a in verified["actions"]]
    assert tickers == ["600519", "09988"]
    kept = verified["actions"][0]
    assert kept["bull_case"] == "정책 수혜"
    assert kept["bear_case"] == "밸류에이션 부담"
    assert kept["verification_confidence"] == 0.8
    assert verified["verified"] is True
    assert verified["verification_dropped"][0]["ticker"] == "000001"


def test_verify_actions_fails_open_on_bad_response():
    analyzer = _analyzer("not json at all {{{")
    result = {
        "summary": "요약",
        "actions": [{"ticker": "600519", "action": "add", "name": "귀주모태주"}],
        "risks": [],
    }
    verified = analyzer._verify_actions("시장뷰", result, [], None)
    assert [a["ticker"] for a in verified["actions"]] == ["600519"]
    assert "verified" not in verified


def test_verify_actions_skips_when_no_add_remove():
    analyzer = _analyzer("ignored")
    result = {"summary": "요약", "actions": [{"ticker": "09988", "action": "keep"}], "risks": []}
    verified = analyzer._verify_actions("시장뷰", result, [], None)
    assert verified is result
