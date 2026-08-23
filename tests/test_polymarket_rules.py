"""선택 게이트와 theme allowlist·polarity 검증(2단계)."""

from datetime import datetime, timedelta, timezone

import pytest

from features.market_sentiment.polymarket import PolymarketContract
from features.market_sentiment.polymarket_rules import (
    RISK_OFF,
    RISK_ON,
    classify_theme,
    select_contracts,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 11, 8, 35, tzinfo=JST)


def _contract(**overrides) -> PolymarketContract:
    values = {
        "condition_id": "0xabc",
        "event_id": "77",
        "question": "Will country A invade country B before 2027?",
        "yes_price": 0.30,
        "spread": 0.02,
        "volume": 250000.0,
        "liquidity": 40000.0,
        "end_date": NOW + timedelta(days=90),
        "active": True,
        "closed": False,
    }
    values.update(overrides)
    return PolymarketContract(**values)


def _select(contract, **overrides):
    options = {
        "min_volume": 10000.0,
        "min_liquidity": 1000.0,
        "max_spread": 0.05,
        "max_horizon_days": 365,
        "moment": NOW,
    }
    options.update(overrides)
    return select_contracts([contract], **options)


# ── polarity ──────────────────────────────────────────

@pytest.mark.parametrize(
    ("question", "theme", "polarity"),
    [
        ("Will Russia invade Poland in 2026?", "military_conflict", RISK_OFF),
        ("Will there be a US military strike on Iran?", "military_conflict", RISK_OFF),
        ("Will the US and China sign a trade deal by June?", "trade_deal", RISK_ON),
        ("Will the US impose new tariffs on the EU?", "trade_restriction", RISK_OFF),
        ("Will the S&P 500 close above 7000 this year?", "equity_upside", RISK_ON),
        ("Will the Nasdaq fall below 18000?", "equity_downside", RISK_OFF),
        ("Will the US enter a recession in 2026?", "macro_stress", RISK_OFF),
        ("Will there be a government shutdown in October?", "macro_stress", RISK_OFF),
    ],
)
def test_allowlisted_questions_get_an_explicit_direction(question, theme, polarity):
    assert classify_theme(question) == (theme, polarity)


def test_invasion_yes_is_inverted_to_risk_off():
    """침공 확률이 오르면 위험선호는 내려간다. 부호를 뒤집지 않으면 반대로 읽힌다."""
    _, polarity = classify_theme("Will Russia invade Poland in 2026?")

    assert polarity == RISK_OFF


@pytest.mark.parametrize(
    "question",
    [
        # 국면 의존: Yes가 좋은지 나쁜지 문구만으로 정해지지 않는다.
        "Will Q3 GDP growth come in between 2% and 3%?",
        "Will the Bank of Korea hold rates in September?",
        "Will the Fed cut rates by 25 basis points?",
        "Will CPI come in below 3%?",
        "Will the unemployment rate exceed 5%?",
        # allowlist에 없는 주제.
        "Highest temperature in Hong Kong on August 11?",
        "Who will win the 2028 presidential election?",
        "Will Bitcoin reach $200k?",
    ],
)
def test_regime_dependent_and_unlisted_questions_are_excluded(question):
    assert classify_theme(question) is None


def test_regime_exclusion_beats_an_allowlist_keyword():
    """allowlist 단어를 품고 있어도 금리 질문이면 넣지 않는다."""
    assert (
        classify_theme("Will the S&P 500 close above 7000 after the FOMC decision?")
        is None
    )


def test_conflicting_directions_are_dropped_rather_than_guessed():
    question = "Will Russia and Ukraine sign a peace deal ending the armed conflict?"

    assert classify_theme(question) is None


def test_blank_question_is_not_classified():
    assert classify_theme("") is None


# ── 게이트 ────────────────────────────────────────────

def test_a_clean_contract_passes_every_gate():
    selected, rejected = _select(_contract())

    assert rejected == {}
    assert len(selected) == 1
    assert selected[0].theme == "military_conflict"
    assert selected[0].polarity == RISK_OFF


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"closed": True}, "closed"),
        ({"active": False}, "inactive"),
        ({"volume": 9999.0}, "volume"),
        ({"liquidity": 999.0}, "liquidity"),
        ({"spread": 0.06}, "spread"),
        ({"end_date": None}, "no_end_date"),
        ({"end_date": NOW - timedelta(days=1)}, "expired"),
        ({"end_date": NOW + timedelta(hours=6)}, "horizon_too_near"),
        ({"end_date": NOW + timedelta(days=400)}, "horizon_too_far"),
        ({"yes_price": 0.995}, "price_extreme"),
        ({"yes_price": 0.005}, "price_extreme"),
        ({"question": "Will it rain in Seoul tomorrow?"}, "no_theme"),
    ],
)
def test_each_gate_rejects_with_its_own_reason(overrides, reason):
    selected, rejected = _select(_contract(**overrides))

    assert selected == []
    assert rejected == {reason: 1}


def test_rejection_reasons_are_counted_for_diagnosis():
    """커버리지가 줄었을 때 게이트 탓인지 마켓 탓인지 구분할 수 있어야 한다."""
    selected, rejected = select_contracts(
        [
            _contract(),
            _contract(condition_id="0x2", liquidity=10.0),
            _contract(condition_id="0x3", liquidity=20.0),
            _contract(condition_id="0x4", question="Best picture winner?"),
        ],
        min_volume=10000.0,
        min_liquidity=1000.0,
        max_spread=0.05,
        max_horizon_days=365,
        moment=NOW,
    )

    assert len(selected) == 1
    assert rejected == {"liquidity": 2, "no_theme": 1}


def test_empty_input_produces_no_selection_and_no_reasons():
    assert select_contracts(
        [],
        min_volume=10000.0,
        min_liquidity=1000.0,
        max_spread=0.05,
        max_horizon_days=365,
        moment=NOW,
    ) == ([], {})
