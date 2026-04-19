from telegram import Update
from telegram.ext import ContextTypes

from src.db.session import SessionLocal
from src.services.alert_service import AlertService


async def alert_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        alerts = AlertService(db).get_alerts()

    if not alerts:
        await update.message.reply_text("등록된 알림이 없습니다.")
        return

    lines = ["*⚠️ 등록된 알림*\n"]
    for a in alerts:
        direction = "이상" if a.condition == "above" else "이하"
        lines.append(f"• {a.ticker}  {float(a.price):,.2f}  {direction}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
