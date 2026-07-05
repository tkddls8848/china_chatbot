"""텔레그램 명령어/콜백 핸들러와 메뉴 구성."""

import asyncio
import logging

from telegram import BotCommand, MenuButtonCommands, Update
from telegram.ext import Application, ContextTypes

from core.config import HELP_TEXT
from research import handle_research_callback
from stocks import StockDatabase
from core.system_control import SystemControlManager
from watchlist import handle_watchlist_callback

logger = logging.getLogger(__name__)


# ── 명령어 핸들러 ─────────────────────────────────────

async def cmd_stockdb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    stock_db: StockDatabase = context.bot_data["stock_db"]
    args = context.args or []
    command = args[0].lower() if args else ""

    if command == "build":
        status = await message.reply_text("종목 DB 빌드 중...")
        try:
            await asyncio.to_thread(stock_db.build)
            total = len(stock_db.get_all())
            await status.edit_text(f"종목 DB 빌드 완료: {total:,}종목")
        except Exception as e:
            logger.exception("[StockDB] build failed")
            await status.edit_text(f"빌드 실패: {e}")
        return

    if command == "enrich":
        status = await message.reply_text("EODHD 시총·업종 보강 중... (수 분 소요)")
        try:
            await asyncio.to_thread(stock_db.enrich)
            enriched = sum(
                1 for v in stock_db.get_all().values()
                if float(v.get("market_cap_cny") or 0) > 0
            )
            total = len(stock_db.get_all())
            await status.edit_text(f"보강 완료: {enriched:,}/{total:,}종목 시총 확보")
        except Exception as e:
            logger.exception("[StockDB] enrich failed")
            await status.edit_text(f"보강 실패: {e}")
        return

    await message.reply_text(
        "<b>stockdb 명령어</b>\n\n"
        "/stockdb build — 종목 코드·이름 목록 갱신\n"
        "/stockdb enrich — EODHD로 시총·업종 보강",
        parse_mode="HTML",
    )


def _format_system_status(system: SystemControlManager, source_lines: list[str] | None = None) -> str:
    if system.gpu_enabled:
        gpu_line = (
            f"GPU 가속: <b>켜짐</b> "
            f"({SystemControlManager.describe(system.num_gpu)}, num_gpu={system.num_gpu})"
        )
    else:
        gpu_line = (
            f"GPU 가속: <b>꺼짐</b> (CPU 전용, "
            f"켜면 {SystemControlManager.describe(system.gpu_on_value)})"
        )
    sources_part = ""
    if source_lines:
        sources_part = "\n\n<b>전역 뉴스 소스</b>\n" + "\n".join(
            f"  {line}" for line in source_lines
        )
    return (
        "<b>시스템 상태</b>\n\n"
        f"{gpu_line}"
        f"{sources_part}\n\n"
        "제어:\n"
        "  /system gpu on — GPU 가속 켜기(자동)\n"
        "  /system gpu off — CPU 전용\n"
        "  /system gpu 레이어수 — 오프로딩 레이어 수 지정"
    )


async def cmd_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    system: SystemControlManager = context.bot_data["system_control"]
    args = context.args or []
    command = args[0].lower() if args else ""

    if command == "gpu":
        value = args[1].lower() if len(args) > 1 else ""
        if value in ("on", "off"):
            system.set_gpu(value == "on")
        elif value.isdigit():
            system.set_gpu_layers(int(value))
        elif value == "":
            await message.reply_text(
                "사용법: /system gpu on | off | <레이어수>", parse_mode="HTML"
            )
            return
        else:
            await message.reply_text(
                "GPU 인자는 on, off 또는 0 이상의 정수여야 합니다.", parse_mode="HTML"
            )
            return
        logger.info("[System] GPU 설정 변경: num_gpu=%d", system.num_gpu)
    elif command:
        await message.reply_text(
            "알 수 없는 항목입니다. 사용법: /system [gpu on|off|<레이어수>]",
            parse_mode="HTML",
        )
        return

    registry = context.bot_data.get("news_registry")
    source_lines = registry.status_lines() if registry is not None else None
    await message.reply_text(
        _format_system_status(system, source_lines), parse_mode="HTML"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if await handle_research_callback(query, context, data):
        return

    if await handle_watchlist_callback(query, context, data):
        return


async def configure_telegram_menu(app: Application) -> None:
    commands = [
        BotCommand("start", "봇 소개와 사용 가능한 경로 보기"),
        BotCommand("menu", "관심종목 삭제/관리 버튼 열기"),
        BotCommand("add", "관심종목 추가: /add 600519"),
        BotCommand("list", "현재 관심종목 목록 보기"),
        BotCommand("research", "리서치 주제 확인/설정/실행"),
        BotCommand("briefing", "모닝/마감 브리핑·성적표 즉시 실행"),
        BotCommand("stockdb", "종목 DB 빌드/EODHD 보강"),
        BotCommand("system", "시스템 상태 보기/GPU 가속 제어"),
        BotCommand("help", "명령어 경로와 설명 보기"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Telegram Menu 버튼 명령어 등록 완료: %s", [cmd.command for cmd in commands])
