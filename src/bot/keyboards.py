from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings


def main_menu() -> InlineKeyboardMarkup:
    url = settings.WEBAPP_URL
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 시장 현황", web_app={"url": f"{url}/index.html"})],
        [InlineKeyboardButton("🔍 종목 검색", web_app={"url": f"{url}/stock.html"})],
        [InlineKeyboardButton("📰 뉴스", web_app={"url": f"{url}/news.html"}),
         InlineKeyboardButton("📅 캘린더", web_app={"url": f"{url}/calendar.html"})],
        [InlineKeyboardButton("⭐ 관심종목", web_app={"url": f"{url}/watchlist.html"}),
         InlineKeyboardButton("⚙️ 설정", web_app={"url": f"{url}/settings.html"})],
    ])


def market_buttons() -> InlineKeyboardMarkup:
    markets = [
        ("상해", "sh_main"), ("선전", "sz_main"),
        ("과창판", "star"), ("창업판", "chinext"), ("홍콩", "hk"),
    ]
    rows = []
    for name, mid in markets:
        rows.append([InlineKeyboardButton(name, callback_data=f"market:{mid}")])
    return InlineKeyboardMarkup(rows)
