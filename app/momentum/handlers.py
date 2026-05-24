import asyncio
import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from momentum.formatter import format_help, format_sector, format_top
from momentum.service import MomentumService

logger = logging.getLogger(__name__)


async def cmd_momentum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    service: MomentumService = context.bot_data["momentum_service"]
    args = context.args or []
    command = args[0].lower() if args else "top"
    logger.info("[Momentum] command received: %s args=%s", command, args)

    if command in {"help", "?"}:
        await message.reply_text(format_help(), parse_mode="HTML")
        return
    if command == "top":
        result = service.get_last_result()
        if result is None:
            await message.reply_text(
                "저장된 모멘텀 결과가 없습니다.\n/momentum refresh 로 먼저 수동 분석을 실행하세요."
            )
            return
        await message.reply_text(
            format_top(result, service.settings.top_limit),
            parse_mode="HTML",
        )
        return
    if command == "sector":
        query = " ".join(args[1:]).strip()
        if not query:
            await message.reply_text("사용법: /momentum sector 업종명")
            return
        result = service.get_last_result()
        if result is None:
            await message.reply_text(
                "저장된 모멘텀 결과가 없습니다.\n/momentum refresh 로 먼저 수동 분석을 실행하세요."
            )
            return
        await message.reply_text(format_sector(result, query), parse_mode="HTML")
        return
    if command in {"refresh", "run"}:
        status = await message.reply_text("모멘텀 데이터를 갱신하고 분석 중입니다...")
        force = any(arg.lower() in {"force", "강제"} for arg in args[1:])
        logger.info("[Momentum] refresh requested force=%s", force)
        lock: asyncio.Lock = context.bot_data.setdefault("momentum_lock", asyncio.Lock())
        async with lock:
            try:
                result = await asyncio.to_thread(service.refresh, force)
            except Exception as e:
                logger.exception("[Momentum] refresh failed")
                await status.edit_text(f"모멘텀 분석 실패: {html.escape(str(e))}", parse_mode="HTML")
                return
        suffix = ""
        if result.get("cache_status") == "cooldown_cached":
            suffix = "\n\n최근 갱신 쿨다운 중이라 저장된 결과를 반환했습니다."
        await status.edit_text(
            format_top(result, service.settings.top_limit) + suffix,
            parse_mode="HTML",
        )
        logger.info(
            "[Momentum] refresh completed sectors=%d errors=%d cache_status=%s",
            len(result.get("sectors") or []),
            len(result.get("errors") or []),
            result.get("cache_status"),
        )
        return

    await message.reply_text(format_help(), parse_mode="HTML")
