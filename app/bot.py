"""봇 진입점: 서비스 구성, 핸들러 등록, 스케줄러 구동."""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from handlers import (
    callback_handler,
    cmd_help,
    cmd_score,
    cmd_start,
    cmd_stockdb,
    cmd_system,
    cmd_view,
    configure_telegram_menu,
)
from core.access import restricted
from core.config import (
    BASE_DIR,
    NEWS_GLOBAL_SOURCE_KEYS,
    NEWS_RSS_FEEDS,
    NEWS_SOURCE_COOLDOWN_MINUTES,
    NEWS_SOURCE_FAILURE_THRESHOLD,
    OLLAMA_BASE_URL,
    OLLAMA_GPU_ON_VALUE,
    OLLAMA_NUM_GPU,
    PREDICTION_LOG_FILE,
    PROMPT_DIR,
    SCHEDULER_INTERVAL_MINUTES,
    SENT_IDS_FILE,
    SENT_NEWS_MAX_IDS,
    SENT_NEWS_RETENTION_DAYS,
    STOCK_DB_ENABLED,
    STOCK_DB_FILE,
    TELEGRAM_BOT_TOKEN,
    TRANSLATION_CONCURRENCY,
    TRANSLATION_ENABLED,
    TRANSLATION_MODEL,
    TRANSLATION_NUM_PREDICT,
    TRANSLATION_TIMEOUT,
    WATCHLIST_FILE,
)
from news import NewsSourceRegistry, build_source_specs
from news.pipeline import fetch_all, refresh_stock_db
from state import PredictionLog, SentNewsTracker
from stocks import StockDatabase
from core.system_control import SystemControlManager
from llm import TranslationService
from watchlist import WatchlistManager, cmd_add, cmd_list, cmd_menu

logger = logging.getLogger(__name__)
_SINGLE_INSTANCE_LOCK = None


def _acquire_single_instance_lock(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


# ── 진입점 ────────────────────────────────────────────

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

    app.bot_data["sent_tracker"]         = SentNewsTracker(SENT_IDS_FILE, SENT_NEWS_MAX_IDS, SENT_NEWS_RETENTION_DAYS)
    app.bot_data["watchlist_manager"]    = WatchlistManager(WATCHLIST_FILE)
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_news_cursor"]    = 0
    app.bot_data["global_news_cursor"]   = 0
    app.bot_data["stock_db"]             = stock_db
    app.bot_data["news_registry"]        = news_registry
    app.bot_data["prediction_log"]       = PredictionLog(PREDICTION_LOG_FILE)
    app.bot_data["translator"]           = TranslationService(
        base_url=OLLAMA_BASE_URL,
        model=TRANSLATION_MODEL,
        enabled=TRANSLATION_ENABLED,
        timeout=TRANSLATION_TIMEOUT,
        prompt_dir=PROMPT_DIR,
        num_gpu=OLLAMA_NUM_GPU,
        num_predict=TRANSLATION_NUM_PREDICT,
    )
    app.bot_data["translate_semaphore"]  = asyncio.Semaphore(TRANSLATION_CONCURRENCY)

    # 런타임 시스템 제어(텔레그램에서 GPU 사용 토글). 세션 한정이며
    # 재시작하면 .env의 OLLAMA_NUM_GPU 값으로 되돌아간다.
    system_control = SystemControlManager(
        default_num_gpu=OLLAMA_NUM_GPU,
        gpu_on_value=OLLAMA_GPU_ON_VALUE,
    )
    system_control.register_consumer(app.bot_data["translator"].set_num_gpu)
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
    app.add_handler(CommandHandler("score",   restricted(cmd_score)))
    app.add_handler(CommandHandler("stockdb", restricted(cmd_stockdb)))
    app.add_handler(CommandHandler("system",  restricted(cmd_system)))
    app.add_handler(CallbackQueryHandler(restricted(callback_handler)))

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
    scheduler.start()

    logger.info(
        "봇 시작됨. %s분마다 전역 뉴스(%s) + 관심종목 뉴스 전송.",
        SCHEDULER_INTERVAL_MINUTES,
        ", ".join(spec.key for spec in news_registry.specs) or "없음",
    )
    logger.info("명령어: /start /help /menu /add /list /view /stockdb /system")
    app.run_polling()


if __name__ == "__main__":
    main()
