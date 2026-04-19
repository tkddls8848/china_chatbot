from telegram import Update
from telegram.ext import ContextTypes

from src.db.session import SessionLocal
from src.services.news_service import NewsService
from src.services.translate_service import enrich_with_translations, translate_pending

SOURCE_LABELS = {"sina": "新浪", "scmp": "SCMP", "reuters": "Reuters", "hkej": "香港经济日报"}


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📰 뉴스 조회 중…")
    with SessionLocal() as db:
        svc = NewsService(db)
        await svc.refresh_cache()
        items = await svc.get_news(limit=10)
        await translate_pending(db, items)
        enrich_with_translations(db, items)

    if not items:
        await update.message.reply_text("뉴스를 불러올 수 없습니다.")
        return

    lines = ["*📰 최신 뉴스*\n"]
    for item in items:
        title_ko = item.get("title_ko", "")
        title_orig = item.get("title", "")
        title = title_ko if title_ko else title_orig
        description_ko = item.get("description_ko", "")
        source = SOURCE_LABELS.get(item.get("source", ""), item.get("source", ""))
        pub = item.get("published", "")
        time_str = pub[11:16] if len(pub) >= 16 else pub[:10]
        meta = f"_{source}  {time_str}_" if source or time_str else ""
        lines.append(f"• *{title}*")
        if title_ko:
            lines.append(f"  _{title_orig}_")
        if description_ko:
            lines.append(description_ko)
        if meta:
            lines.append(meta)
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown")
