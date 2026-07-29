"""score_signals의 StockDB 기반 market 보정 회귀 방지.

뉴스 로그의 market은 기사(출처) 단위로 태깅되어 홍콩/한국 종목이 CN으로
잘못 찍히는 경우가 있다(docs/market_tinker_error.md). score_signals가
StockDatabase의 종목별 market으로 이를 덮어써야 잘못된 시세 조회를 피한다.
"""
from pathlib import Path

from stocks import StockDatabase
from state import scoring


def _stock_db_with(entries: dict[str, dict]) -> StockDatabase:
    db = StockDatabase(cache_file=Path("unused.json"), enabled=False)
    db._db = entries
    return db


def test_score_signals_overrides_market_from_stock_db(monkeypatch):
    stock_db = _stock_db_with(
        {
            "054980": {"market": "KR"},
            "600519": {"market": "CN"},
        }
    )
    signals = [
        # 로그에는 054980이 기사 출처 기반으로 CN이라 잘못 찍혀 있다.
        {"code": "054980", "market": "CN", "date": __import__("datetime").date(2026, 7, 20), "avg": 0.5, "up": True},
        {"code": "600519", "market": "CN", "date": __import__("datetime").date(2026, 7, 20), "avg": 0.5, "up": True},
    ]

    seen_calls: list[tuple[str, str]] = []

    def fake_fetch_closes(code, market, start, end):
        seen_calls.append((code, market))
        return None

    monkeypatch.setattr(scoring, "fetch_market_closes", fake_fetch_closes)

    scoring.score_signals(signals, [1], stock_db=stock_db)

    assert ("054980", "KR") in seen_calls
    assert ("600519", "CN") in seen_calls
    assert [s["market"] for s in signals if s["code"] == "054980"] == ["KR"]


def test_score_signals_falls_back_to_log_market_when_code_unknown(monkeypatch):
    stock_db = _stock_db_with({})  # 코드가 DB에 없음(신규 상장/상장폐지 등)

    signals = [
        {"code": "999999", "market": "CN", "date": __import__("datetime").date(2026, 7, 20), "avg": 0.5, "up": True},
    ]
    seen_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scoring,
        "fetch_market_closes",
        lambda code, market, start, end: seen_calls.append((code, market)) or None,
    )

    scoring.score_signals(signals, [1], stock_db=stock_db)

    assert seen_calls == [("999999", "CN")]


def test_score_signals_without_stock_db_keeps_log_market(monkeypatch):
    signals = [
        {"code": "054980", "market": "CN", "date": __import__("datetime").date(2026, 7, 20), "avg": 0.5, "up": True},
    ]
    seen_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scoring,
        "fetch_market_closes",
        lambda code, market, start, end: seen_calls.append((code, market)) or None,
    )

    scoring.score_signals(signals, [1])

    assert seen_calls == [("054980", "CN")]
