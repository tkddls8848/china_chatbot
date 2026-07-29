"""모닝·마감·주간 브리핑 기능 선언."""

from briefing import (
    TradeCalendar,
    cmd_briefing,
    send_evening_briefing,
    send_morning_briefing,
    send_weekly_scorecard,
)
from core.config import (
    BRIEFING_EVENING_ENABLED,
    BRIEFING_EVENING_HOUR,
    BRIEFING_EVENING_MINUTE,
    BRIEFING_MORNING_ENABLED,
    BRIEFING_MORNING_HOUR,
    BRIEFING_MORNING_MINUTE,
    BRIEFING_LLM_ENABLED,
    BRIEFING_MODEL,
    BRIEFING_PROMPT_FILE,
    BRIEFING_TIMEOUT,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_GPU,
    SCORECARD_DAY_OF_WEEK,
    SCORECARD_ENABLED,
    SCORECARD_HOUR,
)
from features.base import CommandSpec, FeatureSpec, MenuSpec
from llm import BriefingWriter


def _install_services(app) -> None:
    app.bot_data["trade_calendar"] = TradeCalendar()
    app.bot_data["briefing_writer"] = BriefingWriter(
        base_url=OLLAMA_BASE_URL,
        model=BRIEFING_MODEL,
        enabled=BRIEFING_LLM_ENABLED,
        timeout=BRIEFING_TIMEOUT,
        prompt_file=BRIEFING_PROMPT_FILE,
        num_gpu=OLLAMA_NUM_GPU,
    )


def _install_jobs(scheduler, app) -> None:
    if BRIEFING_MORNING_ENABLED:
        scheduler.add_job(
            send_morning_briefing,
            trigger="cron",
            hour=BRIEFING_MORNING_HOUR,
            minute=BRIEFING_MORNING_MINUTE,
            args=[app],
            id="morning_briefing",
            max_instances=1,
            coalesce=True,
        )
    if BRIEFING_EVENING_ENABLED:
        scheduler.add_job(
            send_evening_briefing,
            trigger="cron",
            hour=BRIEFING_EVENING_HOUR,
            minute=BRIEFING_EVENING_MINUTE,
            args=[app],
            id="evening_briefing",
            max_instances=1,
            coalesce=True,
        )
    if SCORECARD_ENABLED:
        scheduler.add_job(
            send_weekly_scorecard,
            trigger="cron",
            day_of_week=SCORECARD_DAY_OF_WEEK,
            hour=SCORECARD_HOUR,
            args=[app],
            id="weekly_scorecard",
            max_instances=1,
            coalesce=True,
        )


FEATURE = FeatureSpec(
    key="briefing",
    label="브리핑",
    requires=frozenset({"news", "watchlist", "research", "quant"}),
    commands=(
        CommandSpec(
            "briefing",
            "브리핑 생성",
            cmd_briefing,
            usage="morning|evening|scorecard",
        ),
    ),
    menus=(
        MenuSpec("📰 브리핑", "nav:briefing", 1, "📰 브리핑", 1),
    ),
    install_services=_install_services,
    install_jobs=_install_jobs,
)
