"""봇 진입점: 서비스 구성, 핸들러 등록, 스케줄러 구동."""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from briefing import (
    TradeCalendar,
    cmd_briefing,
    send_evening_briefing,
    send_morning_briefing,
    send_weekly_scorecard,
)
from handlers import (
    callback_handler,
    cmd_help,
    cmd_market,
    cmd_score,
    cmd_start,
    cmd_stockdb,
    cmd_system,
    cmd_view,
    configure_telegram_menu,
)
from handlers.navigation import handle_menu_text
from core.access import restricted
from core.config import (
    BASE_DIR,
    BRIEFING_EVENING_ENABLED,
    BRIEFING_EVENING_HOUR,
    BRIEFING_EVENING_MINUTE,
    BRIEFING_LLM_ENABLED,
    BRIEFING_MODEL,
    BRIEFING_MORNING_ENABLED,
    BRIEFING_MORNING_HOUR,
    BRIEFING_MORNING_MINUTE,
    BRIEFING_PROMPT_FILE,
    BRIEFING_TIMEOUT,
    NEWS_GLOBAL_SOURCE_KEYS,
    NEWS_LOG_FILE,
    NEWS_LOG_RETENTION_DAYS,
    NEWS_RSS_FEEDS,
    NEWS_SOURCE_COOLDOWN_MINUTES,
    NEWS_SOURCE_FAILURE_THRESHOLD,
    NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS,
    NEWS_STOCK_TRANSLATED_CONTENT_MAX_CHARS,
    OLLAMA_BASE_URL,
    OLLAMA_GPU_ON_VALUE,
    OLLAMA_NUM_GPU,
    PREDICTION_LOG_FILE,
    PROMPT_DIR,
    QUANT_CACHE_TTL_MINUTES,
    QUANT_CONTEXT_ENABLED,
    QUANT_FAILURE_COOLDOWN_MINUTES,
    QUANT_HOT_RANK_ENABLED,
    QUANT_SECTOR_TOP_N,
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
    SCHEDULER_INTERVAL_MINUTES,
    SCORECARD_DAY_OF_WEEK,
    SCORECARD_ENABLED,
    SCORECARD_HOUR,
    SENT_IDS_FILE,
    SENT_NEWS_RETENTION_DAYS,
    STOCK_DB_ENABLED,
    STOCK_DB_FILE,
    TELEGRAM_BOT_TOKEN,
    TRANSLATION_CONCURRENCY,
    TRANSLATION_ENABLED,
    TRANSLATION_MODEL,
    TRANSLATION_NUM_PREDICT,
    TRANSLATION_TIMEOUT,
    WATCHLIST_EVENTS_FILE,
    WATCHLIST_FILE,
)
from news import NewsSourceRegistry, build_source_specs
from news.pipeline import fetch_all, refresh_stock_db
from research import cmd_research, collect_global_market_news_items
from state import NewsLog, PredictionLog, SentNewsTracker
from stocks import QuoteService, StockDatabase
from core.system_control import SystemControlManager
from llm import BriefingWriter, MarketViewAnalyzer, MarketViewManager, TranslationService
from watchlist import WatchlistEventLog, WatchlistManager, cmd_add, cmd_list, cmd_menu

logger = logging.getLogger(__name__)
_SINGLE_INSTANCE_LOCK = None


def _acquire_single_instance_lock(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        handle = lock_file.open("a+b")
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if handle is not None:
            handle.close()
        return None
    return handle


# ── 진입점 ────────────────────────────────────────────

async def _handle_update_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("[TELEGRAM] update processing failed: %s", context.error, exc_info=context.error)


def main() -> None:
    global _SINGLE_INSTANCE_LOCK
    _SINGLE_INSTANCE_LOCK = _acquire_single_instance_lock(BASE_DIR / "data" / "bot.lock")
    if _SINGLE_INSTANCE_LOCK is None:
        logger.error("이미 실행 중인 봇 인스턴스가 있어 시작하지 않습니다.")
        return

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(configure_telegram_menu)
        .build()
    )

    stock_db = StockDatabase(cache_file=STOCK_DB_FILE, enabled=STOCK_DB_ENABLED)
    stock_db.load_or_build()

    news_registry = NewsSourceRegistry(
        build_source_specs(NEWS_GLOBAL_SOURCE_KEYS, NEWS_RSS_FEEDS),
        failure_threshold=NEWS_SOURCE_FAILURE_THRESHOLD,
        cooldown_minutes=NEWS_SOURCE_COOLDOWN_MINUTES,
    )

    app.bot_data["sent_tracker"]         = SentNewsTracker(SENT_IDS_FILE, SENT_NEWS_RETENTION_DAYS)
    app.bot_data["watchlist_manager"]    = WatchlistManager(WATCHLIST_FILE)
    app.bot_data["watchlist_events"]     = WatchlistEventLog(WATCHLIST_EVENTS_FILE)
    app.bot_data["quote_service"]        = QuoteService(
        enabled=QUANT_CONTEXT_ENABLED,
        cache_ttl_minutes=QUANT_CACHE_TTL_MINUTES,
        sector_top_n=QUANT_SECTOR_TOP_N,
        failure_cooldown_minutes=QUANT_FAILURE_COOLDOWN_MINUTES,
        hot_rank_enabled=QUANT_HOT_RANK_ENABLED,
    )
    app.bot_data["market_view_manager"]  = MarketViewManager(RESEARCH_STATE_FILE, history_limit=RESEARCH_HISTORY_LIMIT)
    app.bot_data["research_pending"]     = {}
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_news_cursor"]    = 0
    app.bot_data["global_news_cursor"]   = 0
    app.bot_data["stock_db"]             = stock_db
    app.bot_data["news_registry"]        = news_registry
    app.bot_data["prediction_log"]       = PredictionLog(PREDICTION_LOG_FILE)
    app.bot_data["news_log"]             = NewsLog(NEWS_LOG_FILE, NEWS_LOG_RETENTION_DAYS)
    app.bot_data["trade_calendar"]       = TradeCalendar()
    app.bot_data["translator"]           = TranslationService(
        base_url=OLLAMA_BASE_URL,
        model=TRANSLATION_MODEL,
        enabled=TRANSLATION_ENABLED,
        timeout=TRANSLATION_TIMEOUT,
        prompt_dir=PROMPT_DIR,
        num_gpu=OLLAMA_NUM_GPU,
        num_predict=TRANSLATION_NUM_PREDICT,
        brief_content_limit=NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS,
        stock_brief_content_limit=NEWS_STOCK_TRANSLATED_CONTENT_MAX_CHARS,
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
    app.bot_data["briefing_writer"] = BriefingWriter(
        base_url=OLLAMA_BASE_URL,
        model=BRIEFING_MODEL,
        enabled=BRIEFING_LLM_ENABLED,
        timeout=BRIEFING_TIMEOUT,
        prompt_file=BRIEFING_PROMPT_FILE,
        num_gpu=OLLAMA_NUM_GPU,
    )
    app.bot_data["translate_semaphore"]  = asyncio.Semaphore(TRANSLATION_CONCURRENCY)

    # 리서치 뉴스 수집기는 파이프라인과 같은 소스 레지스트리를 공유한다.
    async def _collect_research_news(translator, translate_semaphore, **kwargs):
        return await collect_global_market_news_items(
            translator, translate_semaphore, news_registry, **kwargs
        )

    app.bot_data["research_news_collector"] = _collect_research_news
    app.add_error_handler(_handle_update_error)

    # 런타임 시스템 제어(텔레그램에서 GPU 사용 토글). 세션 한정이며
    # 재시작하면 .env의 OLLAMA_NUM_GPU 값으로 되돌아간다.
    system_control = SystemControlManager(
        default_num_gpu=OLLAMA_NUM_GPU,
        gpu_on_value=OLLAMA_GPU_ON_VALUE,
    )
    system_control.register_consumer(app.bot_data["translator"].set_num_gpu)
    system_control.register_consumer(app.bot_data["market_view_analyzer"].set_num_gpu)
    system_control.register_consumer(app.bot_data["briefing_writer"].set_num_gpu)
    app.bot_data["system_control"] = system_control
    logger.info(
        "[System] GPU 가속 초기 상태: %s (num_gpu=%d)",
        "켜짐" if system_control.gpu_enabled else "꺼짐(CPU)",
        system_control.num_gpu,
    )

    # ALLOWED_CHAT_IDS가 설정되어 있으면 restricted가 그 외 채팅을 무시한다.
    app.add_handler(CommandHandler("start",   restricted(cmd_start)))
    app.add_handler(CommandHandler("help",    restricted(cmd_help)))
    app.add_handler(CommandHandler("menu",    restricted(cmd_menu)))
    app.add_handler(CommandHandler("add",     restricted(cmd_add)))
    app.add_handler(CommandHandler("list",    restricted(cmd_list)))
    app.add_handler(CommandHandler("view",    restricted(cmd_view)))
    app.add_handler(CommandHandler("market",  restricted(cmd_market)))
    app.add_handler(CommandHandler("score",   restricted(cmd_score)))
    app.add_handler(CommandHandler("research", restricted(cmd_research)))
    app.add_handler(CommandHandler("briefing", restricted(cmd_briefing)))
    app.add_handler(CommandHandler("stockdb", restricted(cmd_stockdb)))
    app.add_handler(CommandHandler("system",  restricted(cmd_system)))
    app.add_handler(CallbackQueryHandler(restricted(callback_handler)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, restricted(handle_menu_text, show_status=False)))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        fetch_all,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        args=[app],
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        refresh_stock_db,
        trigger="cron",
        hour=8,
        minute=30,
        args=[stock_db],
        id="refresh_stock_db",
    )
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
    scheduler.start()

    logger.info(
        "봇 시작됨. %s분마다 전역 뉴스(%s) + 관심종목 뉴스 전송.",
        SCHEDULER_INTERVAL_MINUTES,
        ", ".join(spec.key for spec in news_registry.specs) or "없음",
    )
    logger.info("명령어: /start /help /menu /add /list /view /score /research /briefing /stockdb /system")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    finally:
        if _SINGLE_INSTANCE_LOCK is not None:
            _SINGLE_INSTANCE_LOCK.close()
            _SINGLE_INSTANCE_LOCK = None
