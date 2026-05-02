import asyncio
import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.core import build_list_keyboard, get_services

logger = logging.getLogger(__name__)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    watchlist = await services.watchlist.get_all()
    if not watchlist:
        await update.message.reply_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    await update.message.reply_text(
        "관심종목 관리\n종목 버튼을 누르면 삭제합니다.",
        reply_markup=build_list_keyboard(watchlist),
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    if len(context.args) < 1:
        await update.message.reply_text("사용법: /add 종목코드\n예: /add 300750")
        return

    code = context.args[0].strip()
    if len(context.args) >= 2:
        await update.message.reply_text(f"종목코드만 입력하세요.\n사용법: /add {code}")
        return

    cn_name = services.stock_db.get_cn_name(code)
    if not cn_name:
        await update.message.reply_text(f"{code} 종목명 조회 중...")
        try:
            cn_name = await asyncio.to_thread(services.akshare_client.resolve_stock_name, code)
        except Exception as e:
            logger.error("[WATCHLIST] stock name lookup failed: %s %s", code, e)
            await update.message.reply_text(
                f"{code} 종목명 자동 조회 실패\n종목코드를 확인하고 다시 시도하세요."
            )
            return

    name = await asyncio.to_thread(services.translator.translate_stock_name, cn_name)
    await services.watchlist.add(code, name)
    await update.message.reply_text(f"추가됨: {name} ({code})\n/menu 로 목록 확인")
    logger.info("[WATCHLIST] added: %s %s", code, name)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    watchlist = await services.watchlist.get_all()
    if not watchlist:
        await update.message.reply_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    stock_list = "\n".join(f"  - {name} ({code})" for code, name in watchlist.items())
    await update.message.reply_text(
        f"현재 관심종목\n\n{stock_list}",
        reply_markup=build_list_keyboard(watchlist),
    )


async def handle_remove_callback(query, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    services = get_services(context)
    name = await services.watchlist.remove(code) or code
    logger.info("[WATCHLIST] removed: %s %s", code, name)
    watchlist = await services.watchlist.get_all()
    if not watchlist:
        await query.message.edit_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    await query.message.edit_text(
        f"{html.escape(name)} ({code}) 삭제됨\n\n관심종목 관리",
        reply_markup=build_list_keyboard(watchlist),
    )
