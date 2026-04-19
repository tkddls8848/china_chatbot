from telegram import Update
from telegram.ext import ContextTypes

from src.bot.keyboards import main_menu


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"안녕하세요, {user.first_name}님! 🇨🇳\n"
        "중국·홍콩 증시 정보 봇입니다.\n\n"
        "/market — 시장 현황\n"
        "/news — 최신 뉴스\n"
        "/alert — 가격 알림 목록",
        reply_markup=main_menu(),
    )
