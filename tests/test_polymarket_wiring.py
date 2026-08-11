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
    assert app.bot_data["polymarket_client"].url.endswith("/markets/keyset")
    assert "market_digest_store" in app.bot_data


def test_snapshot_job_is_pinned_to_0835_kst(monkeypatch):
    """하루 변화를 재려면 두 스냅숏이 같은 시각이어야 한다."""
    _, scheduler = _install(monkeypatch, enabled=True)

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["id"] == "polymarket_snapshot"
    assert job["trigger"] == "cron"
    assert (job["hour"], job["minute"]) == (8, 35)
    assert job["timezone"] is KST
    # 기동 즉시 한 번 찍으면 08:35이 아닌 값이 그날 스냅숏이 된다.
    assert "next_run_time" not in job


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

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


def _run_system(bot_data, args):
    message = _Message()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(args=args, bot_data=bot_data)
    asyncio.run(admin.cmd_system(update, context))
    return message.texts[-1]


def test_system_polymarket_reports_that_collection_is_off():
    text = _run_system({}, ["polymarket"])

    assert "POLYMARKET_ENABLED" in text


def test_system_polymarket_lists_every_promotion_gate(monkeypatch):
    class StoreStub:
        async def promotion_report(self, window_days=30):
            return {
                "window_days": 30,
                "criteria": {
                    "snapshot_days": {"value": 28, "threshold": 24, "passed": True},
                    "delta_days": {"value": 20, "threshold": 24, "passed": False},
                },
                "passed": False,
            }

    monkeypatch.setattr(admin, "POLYMARKET_PANEL_ENABLED", False)

    text = _run_system({"polymarket_store": StoreStub()}, ["polymarket"])

    assert "꺼짐(수집만)" in text
    assert "✅ 성공 스냅숏: 28일 (기준 24일)" in text
    assert "❌ 유효 일별 변화: 20일 (기준 24일)" in text
    assert "승격하지 않습니다" in text


def test_system_status_advertises_the_pilot_subcommand():
    text = _run_system({}, [])

    assert "/system polymarket" in text


def test_unknown_system_subcommand_lists_the_available_ones():
    text = _run_system({}, ["nope"])

    assert "features|polymarket" in text
