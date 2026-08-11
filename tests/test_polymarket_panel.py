"""하단 패널·핸들러 회귀 검증(4·5단계).

핵심은 "패널이 없어도 `/market`이 예전 그대로"다. 섀도 기간에는 패널이 꺼져
있고, 켠 뒤에도 수집이 끊기거나 표본이 얇을 수 있다. 그 어느 경우에도 기존
감성 차트와 순위 캡션이 달라지면 안 된다.
"""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from features.market_sentiment import handlers as commands
from features.market_sentiment import snapshot as snapshot_job
from features.market_sentiment.chart import render_market_chart
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

def test_chart_without_consensus_keeps_the_two_panel_layout():
    image = render_market_chart(_ready_series(("CN", "US")), 7)

    assert image.getbuffer().nbytes > 0
    assert image.name == "market_sentiment.png"


def test_explicit_none_consensus_renders_the_same_layout():
    """호출부가 None을 넘겨도 예전 서명과 같은 그림이어야 한다."""
    with_default = render_market_chart(_ready_series(("CN", "US")), 7)
    with_none = render_market_chart(_ready_series(("CN", "US")), 7, None)

    assert with_none.getbuffer().nbytes == pytest.approx(
        with_default.getbuffer().nbytes, rel=0.02
    )


def test_empty_consensus_list_does_not_add_a_panel():
    baseline = render_market_chart(_ready_series(("CN", "US")), 7)
    empty = render_market_chart(_ready_series(("CN", "US")), 7, [])

    assert empty.getbuffer().nbytes == pytest.approx(
        baseline.getbuffer().nbytes, rel=0.02
    )


def test_consensus_adds_a_taller_figure_with_its_own_panel():
    baseline = render_market_chart(_ready_series(("CN", "US")), 7)
    with_panel = render_market_chart(_ready_series(("CN", "US")), 7, _consensus(5))

    assert with_panel.getbuffer().nbytes > baseline.getbuffer().nbytes


# ── 패널 자격 판정 ────────────────────────────────────

class _StoreStub:
    def __init__(self, changes=None, error=None):
        self._changes = changes or []
        self._error = error

    async def daily_changes(self, days):
        if self._error is not None:
            raise self._error
        return self._changes


def _panel(monkeypatch, *, enabled=True, store=None, days=7):
    monkeypatch.setattr(commands, "POLYMARKET_PANEL_ENABLED", enabled)
    monkeypatch.setattr(commands, "today", lambda: TODAY)
    context = SimpleNamespace(
        bot_data={} if store is None else {"polymarket_store": store}
    )
    return asyncio.run(commands._consensus_panel_series(context, days))


def test_panel_is_hidden_while_the_pilot_is_in_shadow_mode(monkeypatch):
    assert _panel(monkeypatch, enabled=False, store=_StoreStub(_consensus(7))) is None


def test_panel_is_hidden_when_collection_is_off(monkeypatch):
    assert _panel(monkeypatch, store=None) is None


def test_panel_needs_more_than_two_points(monkeypatch):
    assert _panel(monkeypatch, store=_StoreStub(_consensus(2))) is None
    assert _panel(monkeypatch, store=_StoreStub(_consensus(3))) is not None


def test_yesterdays_latest_point_is_still_fresh(monkeypatch):
    """스냅숏은 08:35에 찍히므로 오전에는 최신값이 어제치다."""
    series = _consensus(5, last_day=TODAY - timedelta(days=1))

    assert _panel(monkeypatch, store=_StoreStub(series)) is not None


def test_stale_series_is_dropped_instead_of_shown_as_current(monkeypatch):
    series = _consensus(5, last_day=TODAY - timedelta(days=4))

    assert _panel(monkeypatch, store=_StoreStub(series)) is None


def test_store_failure_falls_back_to_no_panel(monkeypatch):
    assert _panel(monkeypatch, store=_StoreStub(error=RuntimeError("disk"))) is None


# ── /market 회귀 ──────────────────────────────────────

class _Status:
    async def edit_text(self, text):
        self.text = text

    async def delete(self):
        self.deleted = True


class _Message:
    async def reply_text(self, text):
        return _Status()

    async def reply_photo(self, **kwargs):
        self.photo = kwargs


def _run_market(monkeypatch, bot_data, *, panel_enabled):
    class DigestStore:
        async def series(self, markets, days):
            return _ready_series(("CN", "US"))

        async def missing_digest_days(self, markets, days):
            return {market: [] for market in markets}

    captured = {}

    async def fake_run_non_urgent(func, *args):
        captured["args"] = args
        return b"chart"

    monkeypatch.setattr(commands, "market_history_gaps", lambda *a, **k: {})
    monkeypatch.setattr(commands, "run_non_urgent", fake_run_non_urgent)
    monkeypatch.setattr(commands, "POLYMARKET_PANEL_ENABLED", panel_enabled)
    monkeypatch.setattr(commands, "today", lambda: TODAY)

    message = _Message()
    update = SimpleNamespace(effective_message=message, callback_query=None)
    context = SimpleNamespace(
        args=["7"],
        bot_data={"market_digest_store": DigestStore(), **bot_data},
    )
    asyncio.run(commands.cmd_market(update, context))
    return message, captured


def test_market_command_is_unchanged_while_the_panel_is_off(monkeypatch):
    message, captured = _run_market(
        monkeypatch,
        {"polymarket_store": _StoreStub(_consensus(7))},
        panel_enabled=False,
    )

    assert captured["args"][2] is None
    caption = message.photo["caption"]
    assert caption.startswith("국가·증시별 뉴스 감성 — 최근 7일")
    assert "Polymarket" not in caption


def test_market_command_survives_a_missing_baseline(monkeypatch):
    message, captured = _run_market(monkeypatch, {}, panel_enabled=True)

    assert captured["args"][2] is None
    assert "Polymarket" not in message.photo["caption"]


def test_market_command_survives_a_broken_consensus_store(monkeypatch):
    message, captured = _run_market(
        monkeypatch,
        {"polymarket_store": _StoreStub(error=RuntimeError("disk"))},
        panel_enabled=True,
    )

    assert captured["args"][2] is None
    assert message.photo["caption"].startswith("국가·증시별 뉴스 감성")


def test_ranking_caption_never_absorbs_the_consensus_value(monkeypatch):
    """외부 확률은 별도 패널에만 그린다. 국가별 점수·순위에 섞이면 안 된다."""
    message, captured = _run_market(
        monkeypatch,
        {"polymarket_store": _StoreStub(_consensus(7))},
        panel_enabled=True,
    )

    assert captured["args"][2] is not None
    caption = message.photo["caption"]
    assert "China mainland +0.10 (40)" in caption
    assert "United States +0.10 (40)" in caption
    assert "위 점수·순위와 무관합니다" in caption


# ── 스냅숏 job 격리 ───────────────────────────────────

class _RecordingStore:
    def __init__(self, accepted=True):
        self.snapshots = []
        self._accepted = accepted

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
