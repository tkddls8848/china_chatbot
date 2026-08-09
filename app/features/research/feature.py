"""시장 리서치 기능 선언."""

from core.config import (
    RESEARCH_HISTORY_LIMIT,
    RESEARCH_STATE_FILE,
)
from features.base import CallbackSpec, CommandSpec, FeatureSpec, MenuSpec
from llm import MarketViewManager, build_market_view_analyzer
from research import (
    cmd_research,
    collect_global_market_news_items,
    handle_research_callback,
)


def _install_services(app) -> None:
    app.bot_data["market_view_manager"] = MarketViewManager(
        RESEARCH_STATE_FILE,
        history_limit=RESEARCH_HISTORY_LIMIT,
    )
    app.bot_data["market_view_analyzer"] = build_market_view_analyzer()
    app.bot_data["research_pending"] = {}

    registry = app.bot_data["news_registry"]

    async def collect_research_news(**kwargs):
        return await collect_global_market_news_items(registry, **kwargs)

    app.bot_data["research_news_collector"] = collect_research_news

FEATURE = FeatureSpec(
    key="research",
    label="시장 리서치",
    requires=frozenset({"news", "watchlist", "instruments", "quant"}),
    commands=(
        CommandSpec(
            "research",
            "리서치 실행",
            cmd_research,
            usage="show|set|run|clear",
        ),
    ),
    menus=(
        MenuSpec("🔎 리서치", "nav:research", 1, "🔎 리서치", 1),
    ),
    callbacks=(
        CallbackSpec(("research_",), handle_research_callback),
    ),
    install_services=_install_services,
    data_files=("data/research/market_research.json",),
)
