"""시장 리서치 기능 선언."""

from core.config import (
    OLLAMA_BASE_URL,
    OLLAMA_NUM_GPU,
    RESEARCH_ANALYSIS_ENABLED,
    RESEARCH_ANALYSIS_MODEL,
    RESEARCH_ANALYSIS_NUM_CTX,
    RESEARCH_ANALYSIS_NUM_PREDICT,
    RESEARCH_ANALYSIS_PROMPT_FILE,
    RESEARCH_ANALYSIS_TIMEOUT,
    RESEARCH_CPU_THREADS,
    RESEARCH_HISTORY_LIMIT,
    RESEARCH_MAX_NEW_ACTIONS,
    RESEARCH_REMOVE_RELEVANCE_THRESHOLD,
    RESEARCH_STATE_FILE,
    RESEARCH_VERIFICATION_ENABLED,
    RESEARCH_VERIFICATION_PROMPT_FILE,
)
from features.base import CommandSpec, FeatureSpec, MenuSpec
from llm import MarketViewAnalyzer, MarketViewManager
from research import cmd_research, collect_global_market_news_items


def _install_services(app) -> None:
    app.bot_data["market_view_manager"] = MarketViewManager(
        RESEARCH_STATE_FILE,
        history_limit=RESEARCH_HISTORY_LIMIT,
    )
    app.bot_data["market_view_analyzer"] = MarketViewAnalyzer(
        base_url=OLLAMA_BASE_URL,
        model=RESEARCH_ANALYSIS_MODEL,
        enabled=RESEARCH_ANALYSIS_ENABLED,
        timeout=RESEARCH_ANALYSIS_TIMEOUT,
        num_predict=RESEARCH_ANALYSIS_NUM_PREDICT,
        num_ctx=RESEARCH_ANALYSIS_NUM_CTX,
        num_thread=RESEARCH_CPU_THREADS,
        prompt_file=RESEARCH_ANALYSIS_PROMPT_FILE,
        num_gpu=OLLAMA_NUM_GPU,
        max_new_actions=RESEARCH_MAX_NEW_ACTIONS,
        remove_relevance_threshold=RESEARCH_REMOVE_RELEVANCE_THRESHOLD,
        verification_enabled=RESEARCH_VERIFICATION_ENABLED,
        verification_prompt_file=RESEARCH_VERIFICATION_PROMPT_FILE,
    )
    app.bot_data["research_pending"] = {}

    registry = app.bot_data["news_registry"]

    async def collect_research_news(
        translator,
        translate_semaphore,
        **kwargs,
    ):
        return await collect_global_market_news_items(
            translator,
            translate_semaphore,
            registry,
            **kwargs,
        )

    app.bot_data["research_news_collector"] = collect_research_news

FEATURE = FeatureSpec(
    key="research",
    label="시장 리서치",
    requires=frozenset({"news", "watchlist", "instruments", "quant"}),
    commands=(CommandSpec("research", "리서치 실행", cmd_research),),
    menus=(
        MenuSpec("🔎 리서치", "nav:research", 1, "🔎 리서치", 1),
    ),
    install_services=_install_services,
    data_files=("data/market_research.json",),
    prompts=(
        "prompts/market_research_ko.txt",
        "prompts/market_research_verify_ko.txt",
    ),
    summary="뉴스·관심종목·정량 데이터를 결합한 시장 분석",
)
