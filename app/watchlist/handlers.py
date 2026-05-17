import asyncio
import html
import logging

import akshare as ak
from telegram import Update
from telegram.ext import ContextTypes

from stock_db import StockDatabase
from translator import TranslationService
from watchlist.keyboards import build_list_keyboard
from watchlist.manager import WatchlistManager

logger = logging.getLogger(__name__)


def _resolve_stock_name(code: str) -> str:
    if len(code) <= 5:
        df = ak.stock_individual_basic_info_hk_xq(symbol=code)
        name = df[df["item"] == "comcnname"]["value"].values[0]
    elif code.startswith(("00", "30")):
        df = ak.stock_individual_basic_info_xq(symbol=f"SZ{code}")
        name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
    elif code.startswith(("60", "68")):
        df = ak.stock_individual_basic_info_xq(symbol=f"SH{code}")
        name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
    else:
        raise ValueError(f"알 수 없는 종목코드 형식: {code}")
    return str(name)


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
            "예: /add 300750"
        )
        return

    code = context.args[0].strip()

    if len(context.args) >= 2:
        await update.message.reply_text(
            f"종목코드만 입력하세요.\n사용법: /add {code}"
        )
        return

    translator: TranslationService = context.bot_data["translator"]

    cn_name = stock_db.get_cn_name(code)
    if cn_name:
        name = await asyncio.to_thread(translator.translate_stock_name, cn_name)
        await wm.add(code, name)
        await update.message.reply_text(f"추가됨: {name} ({code})\n/menu 로 목록 확인")
        logger.info("[WATCHLIST] 추가 (DB): %s %s", code, name)
        return

    await update.message.reply_text(f"{code} 종목명 조회 중...")
    try:
        cn_name = await asyncio.to_thread(_resolve_stock_name, code)
        name = await asyncio.to_thread(translator.translate_stock_name, cn_name)
        await wm.add(code, name)
        await update.message.reply_text(f"추가됨: {name} ({code})\n/menu 로 목록 확인")
        logger.info("[WATCHLIST] 추가 (API): %s %s", code, name)
    except Exception as e:
        logger.error("[WATCHLIST] 종목명 조회 실패: %s %s", code, e)
        await update.message.reply_text(
            f"{code} 종목명 자동 조회 실패\n"
            "종목코드를 확인한 뒤 다시 시도하세요."
        )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    watchlist = await wm.get_all()
    if not watchlist:
        await update.message.reply_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    stock_list = "\n".join(f"  • {name} ({code})" for code, name in watchlist.items())
    await update.message.reply_text(
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
