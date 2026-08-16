"""CLOB 과거 시세 백필 검증.

실제 API를 부르지 않는다. 이력 봉투 파싱, 08:35 표본 추출, 날짜별 게이트,
만기 계약의 탈락, 그리고 백필 결과가 승격 게이트로 이어지는지를 mock으로 본다.
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from core.clock import KST
from features.market_sentiment.polymarket import (
    PolymarketClient,
    PolymarketContract,
    PolymarketError,
    parse_contract,
)
from features.market_sentiment.polymarket_history import (
    PolymarketHistoryClient,
    build_snapshots,
    collect_candidates,
    load_histories,
    parse_price_history,
    sample_price,
    snapshot_moment,
)
from features.market_sentiment.polymarket_history import BackfillCandidate
from state import PolymarketConsensusStore

TODAY = date(2026, 8, 16)


class _Response:
    def __init__(self, payload=None, *, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _contract(**overrides) -> PolymarketContract:
    values = {
        "condition_id": "0xabc",
        "event_id": "77",
        "question": "Will country A invade country B before 2027?",
        "yes_price": 0.30,
        "spread": 0.02,
        "volume": 250000.0,
        "liquidity": 40000.0,
        "end_date": snapshot_moment(TODAY) + timedelta(days=90),
        "active": True,
        "closed": False,
        "yes_token_id": "111",
    }
    values.update(overrides)
    return PolymarketContract(**values)


def _candidate(history, **overrides) -> BackfillCandidate:
    expired = overrides.pop("expired", False)
    theme = overrides.pop("theme", "military_conflict")
    polarity = overrides.pop("polarity", -1)
    return BackfillCandidate(
        contract=_contract(**overrides),
        theme=theme,
        polarity=polarity,
        expired=expired,
        history=history,
    )


def _flat_history(days: int, price: float, *, end_day: date = TODAY):
    """창 전체를 덮는 정시 이력. 하루 한 점이면 표본 추출에 충분하다."""
    return [
        (snapshot_moment(end_day - timedelta(days=offset)) - timedelta(minutes=5), price)
        for offset in range(days, -1, -1)
    ]


# ── 이력 봉투 파싱 ─────────────────────────────────────

def test_history_envelope_is_read_into_kst_points():
    stamp = int(datetime(2026, 8, 15, 8, 30, tzinfo=KST).timestamp())

    points = parse_price_history({"history": [{"t": stamp, "p": 0.42}]})

    assert len(points) == 1
    moment, price = points[0]
    assert price == 0.42
    assert moment.astimezone(KST).hour == 8
    assert moment.astimezone(KST).minute == 30


def test_unexpected_history_envelope_raises_instead_of_emptying():
    """빈 이력과 못 읽은 이력은 다른 사건이다. 조용히 비우면 백필이 거짓말한다."""
    with pytest.raises(PolymarketError) as error:
        parse_price_history({"data": [{"t": 1, "p": 0.5}]})

    assert error.value.reason == "invalid_history"


def test_out_of_range_or_malformed_points_are_dropped():
    stamp = int(datetime(2026, 8, 15, 8, 30, tzinfo=KST).timestamp())

    points = parse_price_history(
        {
            "history": [
                {"t": stamp, "p": 1.4},
                {"t": stamp, "p": "0.5"},
                {"t": None, "p": 0.5},
                "nonsense",
                {"t": stamp, "p": 0.5},
            ]
        }
    )

    assert [price for _stamp, price in points] == [0.5]


def test_history_points_are_sorted_by_time():
    early = int(datetime(2026, 8, 14, 8, 30, tzinfo=KST).timestamp())
    late = int(datetime(2026, 8, 15, 8, 30, tzinfo=KST).timestamp())

    points = parse_price_history(
        {"history": [{"t": late, "p": 0.6}, {"t": early, "p": 0.4}]}
    )

    assert [price for _stamp, price in points] == [0.4, 0.6]


# ── 08:35 표본 ─────────────────────────────────────────

def test_sample_takes_the_last_point_before_the_snapshot_time():
    moment = snapshot_moment(TODAY)
    history = [
        (moment - timedelta(hours=2), 0.40),
        (moment - timedelta(minutes=10), 0.45),
        (moment + timedelta(minutes=10), 0.90),
    ]

    assert sample_price(history, moment) == 0.45


def test_stale_point_is_not_carried_forward():
    """거래가 끊긴 구간을 앞 값으로 채우면 없는 날이 있는 날로 둔갑한다."""
    moment = snapshot_moment(TODAY)
    history = [(moment - timedelta(days=3), 0.40)]

    assert sample_price(history, moment) is None


def test_empty_history_yields_no_sample():
    assert sample_price([], snapshot_moment(TODAY)) is None


def test_snapshot_moment_matches_the_live_job_time():
    moment = snapshot_moment(TODAY)

    assert (moment.hour, moment.minute) == (8, 35)
    assert moment.utcoffset() == timedelta(hours=9)


# ── 날짜별 조립 ────────────────────────────────────────

def _snapshots(candidates, *, window_days=5):
    return build_snapshots(candidates, window_days=window_days, max_horizon_days=365)


def test_every_day_in_the_window_gets_a_snapshot(monkeypatch):
    _freeze(monkeypatch)
    candidates = [_candidate(_flat_history(5, 0.30))]

    snapshots = _snapshots(candidates)

    assert sorted(snapshots) == [TODAY - timedelta(days=offset) for offset in range(5, -1, -1)]
    assert all("0xabc" in day for day in snapshots.values())


def test_spread_is_recorded_only_for_today(monkeypatch):
    """과거 호가는 존재하지 않는다. 0.0으로 채우면 없는 근거가 통과로 둔갑한다."""
    _freeze(monkeypatch)
    candidates = [_candidate(_flat_history(5, 0.30))]

    snapshots = _snapshots(candidates)

    assert snapshots[TODAY]["0xabc"]["spread"] == 0.02
    assert "spread" not in snapshots[TODAY - timedelta(days=3)]["0xabc"]


def test_expired_contract_drops_out_before_its_end_date(monkeypatch):
    """만기 계약을 넣는 이유가 이것이다 — 라이브처럼 짝이 끊겨야 한다."""
    _freeze(monkeypatch)
    end_day = TODAY - timedelta(days=2)
    candidates = [
        _candidate(
            _flat_history(5, 0.30),
            expired=True,
            closed=True,
            end_date=snapshot_moment(end_day),
        )
    ]

    snapshots = _snapshots(candidates)

    # 만기 이틀 전까지만 남는다(만기 임박 구간은 위험선호가 아니라 만기 효과다).
    assert max(snapshots) == end_day - timedelta(days=2)


def test_extreme_price_is_rejected_day_by_day(monkeypatch):
    _freeze(monkeypatch)
    history = _flat_history(5, 0.30)
    # 사흘 전 하루만 사실상 결판난 값이었다고 하자.
    history = [
        (stamp, 0.995 if stamp.date() == TODAY - timedelta(days=3) else price)
        for stamp, price in history
    ]

    snapshots = _snapshots([_candidate(history)])

    assert TODAY - timedelta(days=3) not in snapshots
    assert TODAY in snapshots


def test_days_without_prices_are_skipped(monkeypatch):
    _freeze(monkeypatch)
    history = [
        point
        for point in _flat_history(5, 0.30)
        if point[0].date() != TODAY - timedelta(days=2)
    ]

    snapshots = _snapshots([_candidate(history)])

    assert TODAY - timedelta(days=2) not in snapshots


# ── 후보 수집 ──────────────────────────────────────────

def _gamma_record(**overrides):
    record = {
        "conditionId": "0xabc",
        "question": "Will country A invade country B before 2027?",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.34", "0.66"]),
        "clobTokenIds": json.dumps(["111", "222"]),
        "spread": 0.02,
        "volumeNum": 250000,
        "liquidityNum": 40000,
        "endDate": "2026-12-31T12:00:00Z",
        "active": True,
        "closed": False,
        "events": [{"id": "77", "slug": "geo-risk"}],
    }
    record.update(overrides)
    return record


def test_clob_token_id_is_parsed_from_the_yes_leg():
    """`clobTokenIds`는 `outcomes`와 같은 순서다. No가 먼저 와도 Yes를 집는다."""
    contract = parse_contract(
        _gamma_record(
            outcomes=json.dumps(["No", "Yes"]),
            outcomePrices=json.dumps(["0.66", "0.34"]),
            clobTokenIds=json.dumps(["222", "111"]),
        )
    )

    assert contract.yes_token_id == "111"
    assert contract.yes_price == 0.34


def _collect_client(open_records, expired_records):
    session = _Session(
        [_Response(open_records), _Response(expired_records)]
    )
    return PolymarketClient(
        base_url="https://gamma-api.example",
        timeout=7,
        session=session,
        sleep=lambda _seconds: None,
    )


def _collect(client):
    return collect_candidates(
        client,
        min_volume=10000.0,
        min_liquidity=1000.0,
        max_spread=0.05,
        max_horizon_days=365,
        window_days=30,
    )


def test_expired_candidates_skip_the_liquidity_and_spread_gates():
    """결제 뒤의 유동성·호가로 거르면 만기 관측이 통째로 사라진다."""
    client = _collect_client(
        [],
        [
            _gamma_record(
                conditionId="0xdead",
                closed=True,
                liquidityNum=0,
                spread=0.9,
                clobTokenIds=json.dumps(["333", "444"]),
            )
        ],
    )

    candidates, rejected = _collect(client)

    assert [candidate.contract.condition_id for candidate in candidates] == ["0xdead"]
    assert candidates[0].expired is True
    assert rejected == {}


def test_expired_candidate_still_needs_volume():
    client = _collect_client(
        [], [_gamma_record(conditionId="0xdead", closed=True, volumeNum=10)]
    )

    candidates, rejected = _collect(client)

    assert candidates == []
    assert rejected == {"volume": 1}


def test_open_candidates_keep_the_full_static_gates():
    client = _collect_client([_gamma_record(liquidityNum=10)], [])

    candidates, rejected = _collect(client)

    assert candidates == []
    assert rejected == {"liquidity": 1}


def test_contracts_without_a_token_id_are_counted_separately():
    """토큰 id가 없으면 과거 시세를 부를 키가 없다. 라이브에는 없는 사유다."""
    client = _collect_client([_gamma_record(clobTokenIds=json.dumps([]))], [])

    candidates, rejected = _collect(client)

    assert candidates == []
    assert rejected == {"no_token_id": 1}


def test_open_contract_wins_over_the_expired_duplicate():
    client = _collect_client([_gamma_record()], [_gamma_record(closed=True)])

    candidates, _rejected = _collect(client)

    assert len(candidates) == 1
    assert candidates[0].expired is False


def test_unthemed_questions_are_rejected():
    client = _collect_client([_gamma_record(question="Will it rain in Seoul?")], [])

    candidates, rejected = _collect(client)

    assert candidates == []
    assert rejected == {"no_theme": 1}


# ── 이력 조회 ──────────────────────────────────────────

def test_history_client_asks_for_the_yes_token_over_the_window():
    session = _Session([_Response({"history": []})])
    client = PolymarketHistoryClient(
        base_url="https://clob.example",
        timeout=7,
        session=session,
        sleep=lambda _seconds: None,
    )
    start = snapshot_moment(TODAY - timedelta(days=30))
    end = snapshot_moment(TODAY)

    client.fetch_price_history("111", start=start, end=end)

    call = session.calls[0]
    assert call["url"] == "https://clob.example/prices-history"
    assert call["params"]["market"] == "111"
    assert call["params"]["startTs"] == int(start.timestamp())
    assert call["params"]["endTs"] == int(end.timestamp())
    assert call["params"]["fidelity"] == 60


def test_one_failing_contract_does_not_abort_the_rest():
    stamp = int(snapshot_moment(TODAY - timedelta(days=1)).timestamp())
    session = _Session(
        [
            _Response(None, status_code=422, text="bad token"),
            _Response({"history": [{"t": stamp, "p": 0.5}]}),
        ]
    )
    client = PolymarketHistoryClient(
        base_url="https://clob.example",
        timeout=7,
        session=session,
        sleep=lambda _seconds: None,
    )
    candidates = [
        _candidate([], condition_id="0x1", yes_token_id="1"),
        _candidate([], condition_id="0x2", yes_token_id="2"),
    ]

    failures = load_histories(client, candidates, window_days=30)

    assert failures == {"bad_request": 1}
    assert candidates[0].history == []
    assert len(candidates[1].history) == 1


# ── 승격 게이트로 이어지는지 ───────────────────────────

def test_backfilled_snapshots_feed_the_promotion_report(monkeypatch, tmp_path):
    """백필 결과를 라이브와 같은 store·같은 게이트로 판정한다."""
    _freeze(monkeypatch)
    # store의 창 계산도 같은 "오늘"을 봐야 한다. 실제 날짜에 맡기면 내일 깨진다.
    monkeypatch.setattr("state.polymarket_consensus.today", lambda: TODAY)
    themes = (
        ("military_conflict", -1, "Will country A invade country B before 2027?"),
        ("trade_deal", 1, "Will the US and China sign a trade deal before 2027?"),
        ("macro_stress", -1, "Will a government shutdown begin before 2027?"),
    )
    candidates = []
    for index, (theme, polarity, question) in enumerate(themes):
        for child in range(2):
            candidates.append(
                _candidate(
                    _flat_history(31, 0.30 + 0.01 * index + 0.02 * child),
                    condition_id=f"0x{index}{child}",
                    event_id=f"event-{index}{child}",
                    question=question,
                    theme=theme,
                    polarity=polarity,
                )
            )
    snapshots = build_snapshots(candidates, window_days=31, max_horizon_days=365)

    store = PolymarketConsensusStore(tmp_path / "backfill.json", retention_days=32)

    async def _run():
        for day in sorted(snapshots):
            await store.put_snapshot(day, snapshots[day])
        return await store.promotion_report(window_days=30)

    report = asyncio.run(_run())

    criteria = report["criteria"]
    assert criteria["snapshot_days"]["passed"]
    assert criteria["delta_days"]["passed"]
    assert criteria["dense_day_ratio"]["passed"]
    assert criteria["theme_count"]["value"] == 3
    # 과거 호가가 없으므로 오늘 선정분만 median spread에 들어간다.
    assert criteria["median_spread"]["value"] == 0.02


def _freeze(monkeypatch):
    """`today()`·`now()`를 고정한다. 백필은 창 전체를 오늘 기준으로 센다."""
    frozen = snapshot_moment(TODAY) + timedelta(hours=3)
    monkeypatch.setattr(
        "features.market_sentiment.polymarket_history.today", lambda: TODAY
    )
    monkeypatch.setattr(
        "features.market_sentiment.polymarket_history.now", lambda: frozen
    )


def test_future_snapshot_time_is_not_written(monkeypatch):
    """08:35 이전에 돌리면 오늘은 아직 스냅숏을 만들 수 없다."""
    early = snapshot_moment(TODAY) - timedelta(hours=1)
    monkeypatch.setattr(
        "features.market_sentiment.polymarket_history.today", lambda: TODAY
    )
    monkeypatch.setattr(
        "features.market_sentiment.polymarket_history.now", lambda: early
    )

    snapshots = build_snapshots(
        [_candidate(_flat_history(5, 0.30))], window_days=5, max_horizon_days=365
    )

    assert TODAY not in snapshots
    assert TODAY - timedelta(days=1) in snapshots


def test_history_timestamps_from_utc_land_on_the_right_day():
    """CLOB은 UTC 초를 준다. KST 08:35 표본이 하루 밀리면 안 된다."""
    utc_moment = datetime(2026, 8, 15, 23, 30, tzinfo=timezone.utc)
    points = parse_price_history(
        {"history": [{"t": int(utc_moment.timestamp()), "p": 0.5}]}
    )

    # 2026-08-15 23:30 UTC = 2026-08-16 08:30 KST → 그날 08:35 표본에 잡힌다.
    assert sample_price(points, snapshot_moment(date(2026, 8, 16))) == 0.5
