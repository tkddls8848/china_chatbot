import pytest

from llm.market_view import MarketViewAnalyzer, MarketViewError


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
