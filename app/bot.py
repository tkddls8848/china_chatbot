"""봇 진입점: 서비스 구성, 핸들러 등록, 스케줄러 구동."""

import asyncio
import logging
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application, ContextTypes

from core.config import (
    FEATURES_ENABLED,
    RUNTIME_LOCK_FILE,
    TELEGRAM_BOT_TOKEN,
)
from features import build_feature_registry
from handlers.commands import configure_telegram_menu
from webadmin.server import start_web_admin, stop_web_admin

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

async def _handle_update_error(_update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("[TELEGRAM] update processing failed: %s", context.error, exc_info=context.error)


async def _start_application(app: Application) -> None:
    await configure_telegram_menu(app)
    scheduler = app.bot_data["scheduler"]
    scheduler.start()
    # 웹 서버는 Application 기동 후에만 시작할 수 있어 install_services가
    # 아닌 여기서 기능 활성 여부를 보고 띄운다.
    registry = app.bot_data["feature_registry"]
    if registry.is_enabled("web_admin"):
        await start_web_admin(app)


async def _stop_scheduler(app: Application) -> None:
    await stop_web_admin(app)
    scheduler = app.bot_data.get("scheduler")
    if scheduler is None or not scheduler.running:
        return

    scheduler.pause()
    scheduler.shutdown(wait=False)
    # AsyncIOScheduler.shutdown() schedules cleanup and task cancellation on the
    # event loop. Drain those callbacks before Python starts tearing imports down.
    for _ in range(3):
        await asyncio.sleep(0)
    logger.info("작업 스케줄러를 종료했습니다.")


def main() -> None:
    global _SINGLE_INSTANCE_LOCK
    _SINGLE_INSTANCE_LOCK = _acquire_single_instance_lock(RUNTIME_LOCK_FILE)
    if _SINGLE_INSTANCE_LOCK is None:
        logger.error("이미 실행 중인 봇 인스턴스가 있어 시작하지 않습니다.")
        return

    feature_registry = build_feature_registry(FEATURES_ENABLED)
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_start_application)
        .post_stop(_stop_scheduler)
        .post_shutdown(_stop_scheduler)
        .build()
    )

    app.bot_data["feature_registry"] = feature_registry
    feature_registry.install_services(app)
    app.add_error_handler(_handle_update_error)

    feature_registry.install_telegram_handlers(app)

    scheduler = AsyncIOScheduler()
    app.bot_data["scheduler"] = scheduler
    feature_registry.install_jobs(scheduler, app)

    logger.info(
        "봇 시작됨. 활성 기능: %s",
        ", ".join(sorted(feature_registry.enabled_keys)),
    )
    logger.info(
        "명령어: %s",
        " ".join(f"/{command.command}" for command in feature_registry.telegram_commands()),
    )
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    finally:
        if _SINGLE_INSTANCE_LOCK is not None:
            _SINGLE_INSTANCE_LOCK.close()
            _SINGLE_INSTANCE_LOCK = None
