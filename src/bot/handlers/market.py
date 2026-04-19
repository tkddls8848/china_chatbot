from telegram import Update
from telegram.ext import ContextTypes

from src.db.session import SessionLocal
from src.services.market_service import MarketService

MARKET_EMOJI = {"sh_main": "🔴", "sz_main": "🟠", "star": "⭐", "chinext": "🟢", "hk": "🇭🇰", "hk_tech": "💻"}


async def market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📊 시장 데이터 조회 중…")
    with SessionLocal() as db:
        svc = MarketService(db)
        indices = await svc.get_all_indices()

    lines = ["*📊 중국·홍콩 증시 현황*\n"]
    for idx in indices:
        emoji = MARKET_EMOJI.get(idx["market_id"], "📈")
        sign = "▲" if idx["change_pct"] >= 0 else "▼"
        lines.append(
            f"{emoji} *{idx['name']}*\n"
            f"  {idx['close']:,.2f}  {sign}{abs(idx['change_pct']):.2f}%"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
