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
    cmd_start,
    cmd_stockdb,
    cmd_system,
    configure_telegram_menu,
)
from core.config import (
    BASE_DIR,
    PROMPT_DIR,
    RESEARCH_ANALYSIS_NUM_PREDICT,
    RESEARCH_ANALYSIS_PROMPT_FILE,
    RESEARCH_STATE_FILE,
    RUNTIME_CONFIG_FILE,
    SCHEDULER_INTERVAL_MINUTES,
    SENT_IDS_FILE,
    SENT_NEWS_MAX_IDS,
    SENT_NEWS_RETENTION_DAYS,
    STOCK_DB_ENABLED,
    STOCK_DB_FILE,
    TELEGRAM_BOT_TOKEN,
    TRANSLATION_CONCURRENCY,
    WATCHLIST_FILE,
)
from news.pipeline import fetch_all, refresh_stock_db
from llm import MarketViewAnalyzer, MarketViewManager
from research import cmd_research, collect_global_market_news_items
from state import SentNewsTracker
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

    app.bot_data["sent_tracker"]         = SentNewsTracker(SENT_IDS_FILE, SENT_NEWS_MAX_IDS, SENT_NEWS_RETENTION_DAYS)
    app.bot_data["watchlist_manager"]    = WatchlistManager(WATCHLIST_FILE)
    app.bot_data["market_view_manager"]  = MarketViewManager(RESEARCH_STATE_FILE)
    app.bot_data["research_pending"]     = {}
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_news_cursor"]    = 0
    app.bot_data["global_news_cursor"]   = 0
    app.bot_data["stock_db"]             = stock_db
    ollama_num_gpu = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
    app.bot_data["translator"]           = TranslationService(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("TRANSLATION_MODEL", "gemma4"),
        enabled=os.environ.get("TRANSLATION_ENABLED", "true").lower() == "true",
        timeout=int(os.environ.get("TRANSLATION_TIMEOUT", "60")),
        prompt_dir=PROMPT_DIR,
        num_gpu=ollama_num_gpu,
        num_predict=int(os.environ.get("TRANSLATION_NUM_PREDICT", "768")),
    )
    app.bot_data["market_view_analyzer"] = MarketViewAnalyzer(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get(
            "RESEARCH_ANALYSIS_MODEL",
            os.environ.get("TRANSLATION_MODEL", "gemma4"),
        ),
        enabled=os.environ.get("RESEARCH_ANALYSIS_ENABLED", "true").lower() == "true",
        timeout=int(
            os.environ.get(
                "RESEARCH_ANALYSIS_TIMEOUT",
                os.environ.get("TRANSLATION_TIMEOUT", "180"),
            )
        ),
        num_predict=RESEARCH_ANALYSIS_NUM_PREDICT,
        prompt_file=RESEARCH_ANALYSIS_PROMPT_FILE,
        num_gpu=ollama_num_gpu,
    )
    app.bot_data["translate_semaphore"]  = asyncio.Semaphore(TRANSLATION_CONCURRENCY)
    app.bot_data["research_news_collector"] = collect_global_market_news_items

    # 런타임 시스템 제어(텔레그램에서 GPU 사용 토글). 영속화된 값이 있으면
    # env 기본값 대신 그 값을 두 LLM 서비스에 적용한다.
    ollama_gpu_on_value = int(os.environ.get("OLLAMA_GPU_ON_VALUE", "-1"))
    system_control = SystemControlManager(
        RUNTIME_CONFIG_FILE,
        default_num_gpu=ollama_num_gpu,
        gpu_on_value=ollama_gpu_on_value,
    )
    system_control.register_consumer(app.bot_data["translator"].set_num_gpu)
    system_control.register_consumer(app.bot_data["market_view_analyzer"].set_num_gpu)
    app.bot_data["system_control"] = system_control
    logger.info(
        "[System] GPU 가속 초기 상태: %s (num_gpu=%d)",
        "켜짐" if system_control.gpu_enabled else "꺼짐(CPU)",
        system_control.num_gpu,
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("menu",    cmd_menu))
    app.add_handler(CommandHandler("add",     cmd_add))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("research", cmd_research))
    app.add_handler(CommandHandler("stockdb", cmd_stockdb))
    app.add_handler(CommandHandler("system",  cmd_system))
    app.add_handler(CallbackQueryHandler(callback_handler))

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
        "봇 시작됨. %s분마다 재련사(財联社) + 푸투니우니우(富途牛牛) + 관심종목 뉴스 전송.",
        SCHEDULER_INTERVAL_MINUTES,
    )
    logger.info("명령어: /start /help /menu /add /list /research /stockdb /system")
    app.run_polling()


if __name__ == "__main__":
    main()
