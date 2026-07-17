import html
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from stocks import StockDatabase
from watchlist.keyboards import build_list_keyboard
from watchlist.manager import WatchlistManager

logger = logging.getLogger(__name__)


def _normalize_stock_code(value: str) -> str | None:
    code = value.strip()
    if not re.fullmatch(r"\d{1,6}", code):
        return None
    return code.zfill(5) if len(code) <= 5 else code.zfill(6)


def _unsupported_code_message(code: str) -> str:
    if len(code) == 6 and code.startswith(("300", "301")):
        return "ChiNext(300/301) 종목은 Stock Connect에서 기관 전문투자자 대상이라 제외했습니다."
    if len(code) == 6 and code.startswith(("688", "689")):
        return "STAR Market(688/689) 종목은 Stock Connect에서 기관 전문투자자 대상이라 제외했습니다."
    return "외국인 개인 거래 가능 목록에 없는 종목입니다."


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    watchlist = await wm.get_all()
    if not watchlist:
        await update.message.reply_text(
            "관심종목이 없습니다.\n/add 종목코드 로 추가하세요."
        )
        return
    await update.message.reply_text(
        "<b>관심종목 관리</b>\n종목 버튼을 누르면 삭제됩니다.",
        parse_mode="HTML",
        reply_markup=build_list_keyboard(watchlist),
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    stock_db: StockDatabase = context.bot_data["stock_db"]
    if len(context.args) < 1:
        await update.message.reply_text(
            "사용법: /add 종목코드\n"
            "예: /add 600519"
        )
        return

    code = _normalize_stock_code(context.args[0])
    if code is None:
        await update.message.reply_text("종목코드는 숫자 1~6자리로 입력하세요.")
        return

    if len(context.args) >= 2:
        await update.message.reply_text(
            f"종목코드만 입력하세요.\n사용법: /add {code}"
        )
        return

    name = stock_db.get_display_name(code)
    if not name:
        await update.message.reply_text(
            f"{code} 추가 불가\n{_unsupported_code_message(code)}"
        )
        return

    await wm.add(code, name)
    await update.message.reply_text(f"추가됨: {name} ({code})\n/menu 로 목록 확인")
    logger.info("[WATCHLIST] 추가 (DB): %s %s", code, name)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    message = update.effective_message
    if message is None:
        return
    watchlist = await wm.get_all()
    if not watchlist:
        await message.reply_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    stock_list = "\n".join(f"  • {name} ({code})" for code, name in watchlist.items())
    await message.reply_text(
        f"<b>현재 관심종목</b>\n\n{stock_list}",
        parse_mode="HTML",
        reply_markup=build_list_keyboard(watchlist),
    )


async def handle_watchlist_callback(query, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    if data == "close":
        await query.message.delete()
        return True

    if data == "add_help":
        await query.message.reply_text(
            "추가할 종목을 입력하세요.\n\n"
            "형식: /add 종목코드\n"
            "예시: /add 600519"
        )
        return True

    if data.startswith("remove:"):
        wm: WatchlistManager = context.bot_data["watchlist_manager"]
        code = data.split(":", 1)[1]
        name = await wm.remove(code) or code
        logger.info("[WATCHLIST] 삭제: %s %s", code, name)
        watchlist = await wm.get_all()
        if not watchlist:
            await query.message.edit_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
            return True
        await query.message.edit_text(
            f"<b>{html.escape(name)} ({code}) 삭제됨</b>\n\n"
            "<b>관심종목 관리</b>\n종목 버튼을 누르면 삭제됩니다.",
            parse_mode="HTML",
            reply_markup=build_list_keyboard(watchlist),
        )
        return True

    return False
