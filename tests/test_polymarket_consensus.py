"""스냅숏 저장과 24시간 변화 정렬 검증(3단계)과 승격 게이트 리포트(7단계)."""

import asyncio
import json
from datetime import timedelta

import pytest

from core.clock import today
from state.polymarket_consensus import PolymarketConsensusStore, align_daily_change


def _entry(price, *, polarity=1, theme="trade_deal", event="e1", spread=0.02):
    return {
        "price": price,
        "spread": spread,
        "theme": theme,
        "polarity": polarity,
        "event_id": event,
        "question": "q",
    }


@pytest.fixture
def store(tmp_path):
    return PolymarketConsensusStore(tmp_path / "polymarket_consensus.json", 31)


# ── 일별 정렬 ─────────────────────────────────────────

def test_only_contracts_present_on_both_days_are_compared():
    """만료 계약과 새로 열린 계약을 이어 붙이면 가짜 급변이 만들어진다."""
    change = align_daily_change(
        {"a": _entry(0.40), "expired": _entry(0.90)},
        {"a": _entry(0.45), "brand_new": _entry(0.30)},
    )

    assert change["contract_count"] == 1
    assert change["change_pp"] == pytest.approx(5.0)


def test_polarity_is_applied_so_risk_off_rises_read_as_negative():
    change = align_daily_change(
        {"war": _entry(0.20, polarity=-1, theme="military_conflict")},
        {"war": _entry(0.30, polarity=-1, theme="military_conflict")},
    )

    assert change["change_pp"] == pytest.approx(-10.0)


def test_contract_whose_polarity_changed_is_skipped():
    """규칙 개정으로 부호가 뒤집힌 계약을 이어 붙이면 변화가 아니라 개정을 그린다."""
    change = align_daily_change(
        {"a": _entry(0.40, polarity=1), "b": _entry(0.50, polarity=-1)},
        {"a": _entry(0.45, polarity=-1), "b": _entry(0.55, polarity=-1)},
    )

    assert change["contract_count"] == 1
    assert change["change_pp"] == pytest.approx(-5.0)


def test_no_common_contract_yields_no_value_instead_of_zero():
    assert align_daily_change({"a": _entry(0.4)}, {"b": _entry(0.5)}) is None


def test_child_contracts_of_one_event_collapse_to_a_median():
    """S&P 임계값 8개가 한반도 이벤트 하나보다 8배 세지면 안 된다."""
    previous = {
        **{f"spx{index}": _entry(0.50, event="spx") for index in range(8)},
        "korea": _entry(0.50, polarity=-1, theme="military_conflict", event="korea"),
    }
    current = {
        **{f"spx{index}": _entry(0.60, event="spx") for index in range(8)},
        "korea": _entry(0.60, polarity=-1, theme="military_conflict", event="korea"),
    }

    change = align_daily_change(previous, current)

    assert change["event_count"] == 2
    assert change["contract_count"] == 9
    # 이벤트 하나당 한 표: +10pp와 -10pp가 상쇄된다.
    assert change["change_pp"] == pytest.approx(0.0)
    assert change["themes"]["trade_deal"] == pytest.approx(10.0)
    assert change["themes"]["military_conflict"] == pytest.approx(-10.0)


def test_themes_are_weighted_equally_so_one_topic_cannot_dominate():
    previous = {
        "t1": _entry(0.50, theme="trade_deal", event="t1"),
        "t2": _entry(0.50, theme="trade_deal", event="t2"),
        "t3": _entry(0.50, theme="trade_deal", event="t3"),
        "w1": _entry(0.50, polarity=-1, theme="military_conflict", event="w1"),
    }
    current = {
        "t1": _entry(0.54, theme="trade_deal", event="t1"),
        "t2": _entry(0.54, theme="trade_deal", event="t2"),
        "t3": _entry(0.54, theme="trade_deal", event="t3"),
        "w1": _entry(0.52, polarity=-1, theme="military_conflict", event="w1"),
    }

    change = align_daily_change(previous, current)

    # 이벤트 수가 3:1이어도 theme 평균은 (+4 + -2) / 2 = +1이다.
    assert change["event_count"] == 4
    assert change["themes"] == {
        "trade_deal": pytest.approx(4.0),
        "military_conflict": pytest.approx(-2.0),
    }
    assert change["change_pp"] == pytest.approx(1.0)


def test_contract_without_event_id_counts_as_its_own_event():
    change = align_daily_change(
        {"a": _entry(0.50, event=""), "b": _entry(0.50, event="")},
        {"a": _entry(0.60, event=""), "b": _entry(0.40, event="")},
    )

    assert change["event_count"] == 2
    assert change["change_pp"] == pytest.approx(0.0)


# ── 저장·보존 ─────────────────────────────────────────

def test_snapshot_is_written_once_per_day(store):
    day = today()

    assert asyncio.run(store.put_snapshot(day, {"a": _entry(0.4)})) is True
    # 재실행으로 오후 가격이 들어오면 그날 변화의 기준 시각이 달라진다.
    assert asyncio.run(store.put_snapshot(day, {"a": _entry(0.9)})) is False

    changes = asyncio.run(store.daily_changes(2))
    assert changes == []
    assert asyncio.run(store.snapshot_dates()) == [day]


def test_empty_snapshot_is_not_recorded(store):
    assert asyncio.run(store.put_snapshot(today(), {})) is False
    assert asyncio.run(store.snapshot_dates()) == []


def test_missing_previous_day_leaves_a_hole_instead_of_forward_filling(store):
    day = today()

    async def scenario():
        await store.put_snapshot(day - timedelta(days=3), {"a": _entry(0.30)})
        # 하루(D-2) 수집 실패.
        await store.put_snapshot(day - timedelta(days=1), {"a": _entry(0.50)})
        await store.put_snapshot(day, {"a": _entry(0.55)})
        return await store.daily_changes(7)

    changes = asyncio.run(scenario())

    # D-1에는 전일 스냅숏이 없으므로 값이 없고, 이틀치 변화가 하루로 접히지 않는다.
    assert [change["date"] for change in changes] == [day.isoformat()]
    assert changes[0]["change_pp"] == pytest.approx(5.0)


def test_changes_are_returned_oldest_first(store):
    day = today()

    async def scenario():
        for offset, price in ((3, 0.30), (2, 0.32), (1, 0.35), (0, 0.31)):
            await store.put_snapshot(day - timedelta(days=offset), {"a": _entry(price)})
        return await store.daily_changes(7)

    changes = asyncio.run(scenario())

    assert [change["date"] for change in changes] == [
        (day - timedelta(days=offset)).isoformat() for offset in (2, 1, 0)
    ]


def test_retention_drops_snapshots_outside_the_window(tmp_path):
    path = tmp_path / "polymarket_consensus.json"
    store = PolymarketConsensusStore(path, 31)
    day = today()

    async def scenario():
        await store.put_snapshot(day - timedelta(days=40), {"a": _entry(0.30)})
        await store.put_snapshot(day, {"a": _entry(0.31)})
        return await store.snapshot_dates()

    assert asyncio.run(scenario()) == [day]
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [day.isoformat()]


def test_unreadable_file_starts_empty_instead_of_crashing(tmp_path):
    path = tmp_path / "polymarket_consensus.json"
    path.write_text("{ this is not json", encoding="utf-8")

    store = PolymarketConsensusStore(path, 31)

    assert asyncio.run(store.snapshot_dates()) == []


def test_stored_snapshots_survive_a_restart(tmp_path):
    path = tmp_path / "polymarket_consensus.json"
    day = today()

    async def scenario():
        first = PolymarketConsensusStore(path, 31)
        await first.put_snapshot(day - timedelta(days=1), {"a": _entry(0.40)})
        await first.put_snapshot(day, {"a": _entry(0.44)})
        second = PolymarketConsensusStore(path, 31)
        return await second.daily_changes(7)

    changes = asyncio.run(scenario())

    assert len(changes) == 1
    assert changes[0]["change_pp"] == pytest.approx(4.0)


# ── 승격 게이트 리포트 ────────────────────────────────

def _fill_pilot(store, days, themes=("trade_deal", "military_conflict", "macro_stress")):
    """게이트를 통과하는 모양의 30일 파일럿 데이터를 만든다."""
    day = today()

    async def scenario():
        for offset in range(days, -1, -1):
            contracts = {}
            for index, theme in enumerate(themes):
                for event in range(3):
                    contracts[f"{theme}:{event}"] = _entry(
                        0.50 + 0.001 * offset * (index + 1),
                        theme=theme,
                        event=f"{theme}-{event}",
                    )
            await store.put_snapshot(day - timedelta(days=offset), contracts)
        return await store.promotion_report()

    return asyncio.run(scenario())


def test_a_healthy_pilot_passes_every_gate(store):
    report = _fill_pilot(store, 29)

    criteria = report["criteria"]
    assert criteria["snapshot_days"]["value"] == 30
    assert criteria["delta_days"]["value"] == 29
    assert criteria["dense_day_ratio"]["value"] == 1.0
    assert criteria["theme_count"]["value"] == 3
    assert criteria["median_spread"]["value"] == 0.02
    assert report["passed"] is True


def test_short_pilot_fails_the_coverage_gates(store):
    report = _fill_pilot(store, 5)

    assert report["criteria"]["snapshot_days"]["passed"] is False
    assert report["criteria"]["delta_days"]["passed"] is False
    assert report["passed"] is False


def test_single_theme_pilot_fails_the_concentration_gate(store):
    report = _fill_pilot(store, 29, themes=("trade_deal",))

    assert report["criteria"]["theme_count"]["value"] == 1
    assert report["criteria"]["top_theme_contribution"]["value"] == 1.0
    assert report["criteria"]["top_theme_contribution"]["passed"] is False
    assert report["passed"] is False


def test_empty_store_fails_every_gate_without_crashing(store):
    report = asyncio.run(store.promotion_report())

    assert report["passed"] is False
    assert all(not item["passed"] for item in report["criteria"].values())


# ── 가동률 ────────────────────────────────────────────

def test_uptime_counts_only_the_recent_window(store):
    """라이브가 답하는 유일한 질문이다 — 백필에는 우리 job의 흔적이 없다."""
    day = today()

    async def scenario():
        for offset in (0, 1, 2, 20):
            await store.put_snapshot(day - timedelta(days=offset), {"a": _entry(0.4)})
        return await store.uptime()

    uptime = asyncio.run(scenario())

    # 20일 전 스냅숏은 7일 창 밖이다.
    assert uptime["value"] == 3
    assert uptime["window_days"] == 7
    assert uptime["last_date"] == day.isoformat()


def test_uptime_passes_once_six_of_seven_days_are_captured(store):
    day = today()

    async def scenario(days):
        for offset in range(days):
            await store.put_snapshot(day - timedelta(days=offset), {"a": _entry(0.4)})
        return await store.uptime()

    assert asyncio.run(scenario(5))["passed"] is False
    assert asyncio.run(scenario(6))["passed"] is True


def test_empty_store_reports_no_uptime(store):
    uptime = asyncio.run(store.uptime())

    assert uptime["value"] == 0
    assert uptime["last_date"] == ""
    assert uptime["passed"] is False
