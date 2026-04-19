from telegram import Update
from telegram.ext import ContextTypes

from src.db.session import SessionLocal
from src.services.news_service import NewsService


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📰 뉴스 조회 중…")
    with SessionLocal() as db:
        svc = NewsService(db)
        items = await svc.get_news(limit=5)

    if not items:
        await update.message.reply_text("뉴스를 불러올 수 없습니다.")
        return

    lines = ["*📰 최신 뉴스*\n"]
    for item in items:
        title = item.get("新闻标题", item.get("title", ""))
        lines.append(f"• {title}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
