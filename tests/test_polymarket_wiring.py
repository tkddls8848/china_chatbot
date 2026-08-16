"""기능 조립과 관리 명령 검증(4·6·7단계).

수집(`POLYMARKET_ENABLED`)과 표시(`POLYMARKET_PANEL_ENABLED`)가 따로 움직이는지,
스냅숏 job이 08:35 KST로 고정되는지, `/system polymarket`이 승격 게이트를 그대로
보여 주는지 본다.
"""

import asyncio
from types import SimpleNamespace

from core.clock import KST
from features.market_sentiment import feature as market_feature
from features.system_admin import handlers as admin


class _Scheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, **kwargs):
        self.jobs.append({"func": func, **kwargs})


def _install(monkeypatch, *, enabled):
    monkeypatch.setattr(market_feature, "POLYMARKET_ENABLED", enabled)
    monkeypatch.setattr(
        market_feature, "build_market_digest_analyzer", lambda: object()
    )
    app = SimpleNamespace(bot_data={})
    market_feature._install_services(app)
    scheduler = _Scheduler()
    market_feature._install_jobs(scheduler, app)
    return app, scheduler


def test_collection_off_installs_neither_store_nor_job(monkeypatch):
    app, scheduler = _install(monkeypatch, enabled=False)

    assert "polymarket_store" not in app.bot_data
    assert "polymarket_client" not in app.bot_data
    assert scheduler.jobs == []
    # 기존 감성 서비스는 그대로 있어야 한다.
    assert "market_digest_store" in app.bot_data


def test_collection_on_installs_the_external_source_of_market_sentiment(monkeypatch):
    app, scheduler = _install(monkeypatch, enabled=True)

    assert "polymarket_store" in app.bot_data
    assert app.bot_data["polymarket_client"].url.endswith("/markets")
    assert "market_digest_store" in app.bot_data


def test_snapshot_job_is_pinned_to_0835_kst(monkeypatch):
    """하루 변화를 재려면 두 스냅숏이 같은 시각이어야 한다.

    다만 08:35 한 번만 노리면 그 순간의 재시작 하나로 하루가 빈다. 10:35까지
    재시도하되 그 이상 늦은 값은 하루 축에 얹지 않는다.
    """
    _, scheduler = _install(monkeypatch, enabled=True)

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["id"] == "polymarket_snapshot"
    assert job["trigger"] == "cron"
    assert (job["hour"], job["minute"]) == ("8-10", 35)
    assert job["timezone"] is KST
    # 기동 즉시 한 번 찍으면 08:35이 아닌 값이 그날 스냅숏이 된다.
    assert "next_run_time" not in job


def test_retry_window_skips_the_fetch_once_the_day_is_captured(monkeypatch):
    """재시도 창의 2·3회차는 조회 없이 끝나야 한다."""
    from datetime import date

    from features.market_sentiment import snapshot as snapshot_module

    calls = []

    class ClientStub:
        def fetch_open_contracts(self, **kwargs):
            calls.append(kwargs)
            return []

    class StoreStub:
        async def snapshot_dates(self):
            return [date(2026, 8, 15)]

    monkeypatch.setattr(snapshot_module, "today", lambda: date(2026, 8, 15))
    app = SimpleNamespace(
        bot_data={"polymarket_client": ClientStub(), "polymarket_store": StoreStub()}
    )

    asyncio.run(snapshot_module.capture_polymarket_snapshot(app))

    assert calls == []


def test_cron_without_an_explicit_timezone_would_follow_the_host():
    """서버를 다른 타임존에 올리면 스냅숏 시각이 통째로 밀린다.

    `timezone=KST`를 빼면 APScheduler가 호스트 타임존을 쓴다. 그러면 하루 변화가
    날마다 다른 시각의 가격 차이가 되어 같은 축에 놓을 수 없다.
    """
    from datetime import datetime, timezone

    from apscheduler.triggers.cron import CronTrigger

    after = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
    pinned = CronTrigger(hour=8, minute=35, timezone=KST)

    fire = pinned.get_next_fire_time(None, after).astimezone(timezone.utc)

    # 08:35 KST = 전날 23:35 UTC.
    assert (fire.hour, fire.minute) == (23, 35)


def test_polymarket_stays_inside_market_sentiment_instead_of_a_new_feature():
    from features import ALL_FEATURES

    keys = {spec.key for spec in ALL_FEATURES}

    assert "polymarket" not in keys
    assert "data/market_sentiment/polymarket_consensus.json" in dict(
        (spec.key, spec.data_files) for spec in ALL_FEATURES
    )["market_sentiment"]


# ── /system polymarket ────────────────────────────────

class _Message:
    def __init__(self):
        self.texts = []
        self.markups = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))


def _run_system(bot_data, args):
    message = _Message()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(args=args, bot_data=bot_data)
    asyncio.run(admin.cmd_system(update, context))
    return message.texts[-1]


class _UptimeStore:
    def __init__(self, value=6, passed=True):
        self._value = value
        self._passed = passed

    async def uptime(self, window_days=7):
        return {
            "window_days": window_days,
            "value": self._value,
            "threshold": 6,
            "passed": self._passed,
            "last_date": "2026-08-16",
        }


def _backfill_report(passed=False):
    return {
        "window_days": 30,
        "criteria": {
            "snapshot_days": {"value": 28, "threshold": 24, "passed": True},
            "delta_days": {"value": 20, "threshold": 24, "passed": passed},
        },
        "passed": passed,
    }


class _BackfillStore:
    def __init__(self, passed=False):
        self._passed = passed

    async def promotion_report(self, window_days=30):
        return _backfill_report(self._passed)


def test_system_polymarket_reports_that_nothing_has_started(monkeypatch):
    monkeypatch.setattr(admin, "_backfill_store", lambda: None)

    text = _run_system({}, ["polymarket"])

    assert "POLYMARKET_ENABLED" in text


def test_system_polymarket_shows_uptime_and_backfill_side_by_side(monkeypatch):
    """수집과 백필은 서로를 대신하지 못한다. 한 화면에 둘 다 있어야 한다."""
    monkeypatch.setattr(admin, "POLYMARKET_PANEL_ENABLED", False)
    monkeypatch.setattr(admin, "_backfill_store", _BackfillStore)

    text = _run_system({"polymarket_store": _UptimeStore()}, ["polymarket"])

    assert "꺼짐(수집만)" in text
    assert "✅ 최근 7일 스냅숏: 6일 (기준 6일)" in text
    assert "마지막 스냅숏: 2026-08-16" in text
    assert "✅ 성공 스냅숏: 28일 (기준 24일)" in text
    assert "❌ 유효 일별 변화: 20일 (기준 24일)" in text
    assert "승격하지 않습니다" in text


def test_backfill_caveats_are_shown_next_to_the_gate(monkeypatch):
    """백필이 판정하지 못하는 항목을 통과로 읽으면 안 된다."""
    monkeypatch.setattr(admin, "_backfill_store", _BackfillStore)

    text = _run_system({"polymarket_store": _UptimeStore()}, ["polymarket"])

    assert "job 가동률은 라이브에서 확인" in text


def test_promotion_needs_both_uptime_and_backfill(monkeypatch):
    monkeypatch.setattr(admin, "_backfill_store", lambda: _BackfillStore(passed=True))

    passing = _run_system({"polymarket_store": _UptimeStore()}, ["polymarket"])
    short_uptime = _run_system(
        {"polymarket_store": _UptimeStore(value=3, passed=False)}, ["polymarket"]
    )

    assert "승격할 수 있습니다" in passing
    assert "승격하지 않습니다" in short_uptime


def test_backfill_alone_is_reported_while_collection_is_still_off(monkeypatch):
    """백필을 먼저 돌리고 수집을 나중에 켜도 화면이 비지 않는다."""
    monkeypatch.setattr(admin, "_backfill_store", _BackfillStore)

    text = _run_system({}, ["polymarket"])

    assert "수집이 꺼져 있습니다" in text
    assert "❌ 유효 일별 변화" in text


def test_collection_without_a_backfill_says_so(monkeypatch):
    monkeypatch.setattr(admin, "_backfill_store", lambda: None)

    text = _run_system({"polymarket_store": _UptimeStore()}, ["polymarket"])

    assert "백필을 아직 돌리지 않았습니다" in text


def test_system_status_advertises_the_pilot_subcommand():
    text = _run_system({}, [])

    assert "/system polymarket" in text


def test_unknown_system_subcommand_lists_the_available_ones():
    text = _run_system({}, ["nope"])

    assert "features|polymarket" in text


def test_system_status_carries_a_polymarket_button():
    """파일럿 진행 상황을 명령 인자 없이 열 수 있어야 한다."""
    message = _Message()
    update = SimpleNamespace(effective_message=message)
    asyncio.run(admin.cmd_system(update, SimpleNamespace(args=[], bot_data={})))

    buttons = [
        button
        for row in message.markups[-1].inline_keyboard
        for button in row
    ]
    assert "nav:system:polymarket" in {button.callback_data for button in buttons}


def test_menu_button_routes_to_the_polymarket_report(monkeypatch):
    """버튼은 `/system polymarket`과 같은 경로를 타야 한다."""
    from handlers import navigation

    seen = {}

    async def fake_cmd_system(update, context):
        seen["args"] = context.args

    monkeypatch.setattr(
        "features.system_admin.handlers.cmd_system", fake_cmd_system
    )
    query = SimpleNamespace(message=_Message())
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(
        args=[],
        bot_data={"feature_registry": SimpleNamespace(menu_owner=lambda _data: None)},
        user_data={},
        application=None,
    )

    handled = asyncio.run(
        navigation.handle_menu_callback(update, context, "nav:system:polymarket")
    )

    assert handled is True
    assert seen["args"] == ["polymarket"]
