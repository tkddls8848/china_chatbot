"""폴리마켓 차트·핸들러 회귀 검증(4·5단계, 2026-08-29 독립 명령으로 분리).

`/market`은 폴리마켓을 전혀 모른다 — 하단 패널이었던 시절과 달리 지금은
`/polymarket`이 같은 데이터로 완전히 별도의 차트를 그린다. 핵심은 둘이 서로
영향을 주지 않는다는 것: `/market`은 폴리마켓 수집이 꺼져 있든 얇든 항상 같은
2패널 차트이고, `/polymarket`은 데이터가 부족하면 차트 대신 안내 메시지를
낸다.
"""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

from features.market_sentiment import handlers as commands
from features.market_sentiment import snapshot as snapshot_job
from features.market_sentiment.chart import render_market_chart, render_polymarket_chart
from features.market_sentiment.polymarket import PolymarketError


TODAY = date(2026, 8, 11)


def _ready_series(markets):
    return {
        market: {
            "avg_sentiment": 0.1,
            "count": 40,
            "daily": [
                {"date": TODAY.isoformat(), "avg_sentiment": 0.1, "count": 20},
                {
                    "date": (TODAY - timedelta(days=1)).isoformat(),
                    "avg_sentiment": -0.1,
                    "count": 20,
                },
            ],
        }
        for market in markets
    }


def _consensus(days, *, last_day=TODAY):
    return [
        {
            "date": (last_day - timedelta(days=offset)).isoformat(),
            "change_pp": 1.5 if offset % 2 else -0.8,
        }
        for offset in reversed(range(days))
    ]


# ── 차트 ──────────────────────────────────────────────

def test_market_chart_takes_no_polymarket_argument():
    """`/market`은 더 이상 폴리마켓을 알지 못한다 — 시그니처에도 없다."""
    image = render_market_chart(_ready_series(("CN", "US")), 7)

    assert image.getbuffer().nbytes > 0
    assert image.name == "market_sentiment.png"


def test_polymarket_chart_renders_its_own_figure():
    image = render_polymarket_chart(_consensus(7), 7)

    assert image.getbuffer().nbytes > 0
    assert image.name == "polymarket_consensus.png"


# ── 자격 판정(`_polymarket_series`) ────────────────────

class _StoreStub:
    def __init__(self, changes=None, error=None):
        self._changes = changes or []
        self._error = error

    async def daily_changes(self, days):
        if self._error is not None:
            raise self._error
        return self._changes


def _series(monkeypatch, *, enabled=True, store=None, days=7):
    monkeypatch.setattr(commands, "POLYMARKET_PANEL_ENABLED", enabled)
    monkeypatch.setattr(commands, "today", lambda: TODAY)
    context = SimpleNamespace(
        bot_data={} if store is None else {"polymarket_store": store}
    )
    return asyncio.run(commands._polymarket_series(context, days))


def test_series_is_hidden_while_the_pilot_is_in_shadow_mode(monkeypatch):
    assert _series(monkeypatch, enabled=False, store=_StoreStub(_consensus(7))) is None


def test_series_is_hidden_when_collection_is_off(monkeypatch):
    assert _series(monkeypatch, store=None) is None


def test_series_needs_more_than_two_points(monkeypatch):
    assert _series(monkeypatch, store=_StoreStub(_consensus(2))) is None
    assert _series(monkeypatch, store=_StoreStub(_consensus(3))) is not None


def test_yesterdays_latest_point_is_still_fresh(monkeypatch):
    """스냅숏은 08:35에 찍히므로 오전에는 최신값이 어제치다."""
    series = _consensus(5, last_day=TODAY - timedelta(days=1))

    assert _series(monkeypatch, store=_StoreStub(series)) is not None


def test_stale_series_is_dropped_instead_of_shown_as_current(monkeypatch):
    series = _consensus(5, last_day=TODAY - timedelta(days=4))

    assert _series(monkeypatch, store=_StoreStub(series)) is None


def test_store_failure_falls_back_to_no_series(monkeypatch):
    assert _series(monkeypatch, store=_StoreStub(error=RuntimeError("disk"))) is None


# ── /market 회귀: 폴리마켓을 완전히 모른다 ──────────────

class _Status:
    async def edit_text(self, text):
        self.text = text

    async def delete(self):
        self.deleted = True


class _Message:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return _Status()

    async def reply_photo(self, **kwargs):
        self.photo = kwargs


def _run_market(monkeypatch, bot_data=None):
    class DigestStore:
        async def series(self, markets, days):
            return _ready_series(("CN", "US"))

        async def missing_digest_days(self, markets, days):
            return {market: [] for market in markets}

    captured = {}

    async def fake_run_non_urgent(func, *args):
        captured["func"] = func
        captured["args"] = args
        return b"chart"

    monkeypatch.setattr(commands, "market_history_gaps", lambda *a, **k: {})
    monkeypatch.setattr(commands, "run_non_urgent", fake_run_non_urgent)
    monkeypatch.setattr(commands, "today", lambda: TODAY)

    message = _Message()
    update = SimpleNamespace(effective_message=message, callback_query=None)
    context = SimpleNamespace(
        args=["7"],
        bot_data={"market_digest_store": DigestStore(), **(bot_data or {})},
    )
    asyncio.run(commands.cmd_market(update, context))
    return message, captured


def test_market_command_never_touches_the_polymarket_store(monkeypatch):
    """`polymarket_store`가 있어도, 얇거나 깨져 있어도 `/market`은 신경 쓰지 않는다."""
    message, captured = _run_market(
        monkeypatch, {"polymarket_store": _StoreStub(_consensus(7))}
    )

    markets, days = captured["args"]
    assert captured["func"] is commands.render_market_chart
    assert set(markets) == {"CN", "US"}
    assert days == 7
    caption = message.photo["caption"]
    assert caption.startswith("국가·증시별 뉴스 감성 — 최근 7일")
    assert "Polymarket" not in caption
    assert "폴리마켓" not in caption


def test_market_command_survives_a_broken_polymarket_store(monkeypatch):
    message, _captured = _run_market(
        monkeypatch, {"polymarket_store": _StoreStub(error=RuntimeError("disk"))}
    )

    assert message.photo["caption"].startswith("국가·증시별 뉴스 감성")


# ── `/polymarket` 차트 ──────────────────────────────────

def _run_polymarket_chart(monkeypatch, *, store=None, args=("7",), panel_enabled=True):
    captured = {}

    async def fake_run_non_urgent(func, *fn_args):
        captured["func"] = func
        captured["args"] = fn_args
        return b"chart"

    monkeypatch.setattr(commands, "run_non_urgent", fake_run_non_urgent)
    monkeypatch.setattr(commands, "POLYMARKET_PANEL_ENABLED", panel_enabled)
    monkeypatch.setattr(commands, "today", lambda: TODAY)

    message = _Message()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(
        args=list(args),
        bot_data={} if store is None else {"polymarket_store": store},
    )
    asyncio.run(commands.cmd_polymarket(update, context))
    return message, captured


def test_polymarket_chart_renders_when_data_is_sufficient(monkeypatch):
    message, captured = _run_polymarket_chart(
        monkeypatch, store=_StoreStub(_consensus(7))
    )

    assert captured["func"] is commands.render_polymarket_chart
    assert "최근 7일" in message.photo["caption"]
    assert "pp" in message.photo["caption"]


def test_polymarket_chart_explains_insufficient_data_instead_of_erroring(monkeypatch):
    message, _captured = _run_polymarket_chart(monkeypatch, store=None)

    assert not hasattr(message, "photo")
    assert any("데이터가 없습니다" in text for text in message.replies)


def test_polymarket_gate_keyword_still_reaches_the_diagnostic_report(monkeypatch):
    monkeypatch.setattr(commands, "_backfill_store", lambda: None)

    message, _captured = _run_polymarket_chart(monkeypatch, store=None, args=("gate",))

    assert any("POLYMARKET_ENABLED" in text for text in message.replies)


def test_polymarket_rejects_an_out_of_range_day_count(monkeypatch):
    message, _captured = _run_polymarket_chart(monkeypatch, args=("40",))

    assert any("1~30일" in text for text in message.replies)


# ── 스냅숏 job 격리 ───────────────────────────────────

class _RecordingStore:
    def __init__(self, accepted=True, captured_days=()):
        self.snapshots = []
        self._accepted = accepted
        # job이 재시도 창에서 조회를 건너뛸지 판단할 때 읽는다.
        self._captured_days = list(captured_days)

    async def snapshot_dates(self):
        return list(self._captured_days)

    async def put_snapshot(self, day, contracts):
        self.snapshots.append((day, contracts))
        return self._accepted


class _ClientStub:
    def __init__(self, contracts=None, error=None):
        self._contracts = contracts or []
        self._error = error

    def fetch_open_contracts(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._contracts


def _app(client, store):
    return SimpleNamespace(
        bot_data={"polymarket_client": client, "polymarket_store": store}
    )


def _live_contract(**overrides):
    from core.clock import now
    from features.market_sentiment.polymarket import PolymarketContract

    values = {
        "condition_id": "0xabc",
        "event_id": "77",
        "question": "Will country A invade country B before 2027?",
        "yes_price": 0.30,
        "spread": 0.02,
        "volume": 250000.0,
        "liquidity": 40000.0,
        "end_date": now() + timedelta(days=90),
        "active": True,
        "closed": False,
    }
    values.update(overrides)
    return PolymarketContract(**values)


def test_snapshot_stores_selected_contracts_with_their_polarity():
    store = _RecordingStore()
    client = _ClientStub([_live_contract(), _live_contract(condition_id="0x2", liquidity=1.0)])

    asyncio.run(snapshot_job.capture_polymarket_snapshot(_app(client, store)))

    assert len(store.snapshots) == 1
    day, contracts = store.snapshots[0]
    assert day == commands.today()
    # 게이트에서 떨어진 계약은 스냅숏에 남지 않는다.
    assert set(contracts) == {"0xabc"}
    assert contracts["0xabc"]["polarity"] == -1
    assert contracts["0xabc"]["theme"] == "military_conflict"
    assert contracts["0xabc"]["price"] == 0.30
    assert contracts["0xabc"]["spread"] == 0.02
    assert contracts["0xabc"]["event_id"] == "77"


def test_snapshot_skips_a_day_that_is_already_captured():
    store = _RecordingStore(accepted=False)

    asyncio.run(
        snapshot_job.capture_polymarket_snapshot(
            _app(_ClientStub([_live_contract()]), store)
        )
    )

    assert len(store.snapshots) == 1


def test_unclassifiable_contracts_never_reach_the_snapshot():
    """allowlist에 없는 질문이 조용히 섞여 들어오는 쪽이 결측보다 나쁘다."""
    store = _RecordingStore()
    client = _ClientStub(
        [_live_contract(question="Highest temperature in Hong Kong today?")]
    )

    asyncio.run(snapshot_job.capture_polymarket_snapshot(_app(client, store)))

    assert store.snapshots == []


def test_snapshot_job_swallows_api_failures():
    """외부 소스 하나의 실패가 다른 스케줄 작업으로 번지면 안 된다."""
    store = _RecordingStore()

    asyncio.run(
        snapshot_job.capture_polymarket_snapshot(
            _app(_ClientStub(error=PolymarketError("timeout", retryable=True)), store)
        )
    )

    assert store.snapshots == []


def test_snapshot_job_records_nothing_when_no_contract_passes_the_gates():
    store = _RecordingStore()

    asyncio.run(snapshot_job.capture_polymarket_snapshot(_app(_ClientStub([]), store)))

    assert store.snapshots == []


def test_snapshot_job_is_a_no_op_when_collection_is_off():
    asyncio.run(
        snapshot_job.capture_polymarket_snapshot(SimpleNamespace(bot_data={}))
    )
