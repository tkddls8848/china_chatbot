"""시작·도움말·시스템 제어 명령 구현."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.system_control import SystemControlManager
from handlers.navigation import main_menu, persistent_menu

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    registry = context.bot_data["feature_registry"]
    await update.message.reply_text(
        registry.help_text(),
        parse_mode="HTML",
        reply_markup=persistent_menu(registry),
    )
    await update.message.reply_text(
        "원하는 기능을 선택하세요.",
        reply_markup=main_menu(registry),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


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
    feature_registry = context.bot_data.get("feature_registry")

    if command == "features":
        lines = (
            feature_registry.catalog_lines()
            if feature_registry is not None
            else ["기능 레지스트리가 준비되지 않았습니다."]
        )
        await message.reply_text(
            "<b>기능 카탈로그</b>\n" + "\n".join(f"  {line}" for line in lines),
            parse_mode="HTML",
        )
        return

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
            "알 수 없는 항목입니다. 사용법: /system [features|gpu on|off|<레이어수>]",
            parse_mode="HTML",
        )
        return

    registry = context.bot_data.get("news_registry")
    source_lines = registry.status_lines() if registry is not None else None
    await message.reply_text(
        _format_system_status(system, source_lines), parse_mode="HTML"
    )
