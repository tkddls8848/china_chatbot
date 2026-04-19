import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from src.config import settings
from src.db.models.alert import Alert
from src.db.session import SessionLocal
from src.services.alert_service import AlertService
from src.services.market_service import MarketService
from src.services.news_service import NewsService
from src.services.translate_service import translate_pending

logger = logging.getLogger(__name__)


async def refresh_index_cache() -> None:
    with SessionLocal() as db:
        await MarketService(db).get_all_indices()
    logger.info("index cache refreshed")


async def refresh_rss_feeds() -> None:
    with SessionLocal() as db:
        await NewsService(db).refresh_cache()
    logger.info("rss feeds refreshed")


async def translate_news() -> None:
    with SessionLocal() as db:
        svc = NewsService(db)
        items = await svc.get_news(limit=200)
        count = await translate_pending(db, items)
    if count:
        logger.info("번역 잡 완료: %d건", count)


async def check_price_alerts(bot: Bot) -> None:
    with SessionLocal() as db:
        triggered = await AlertService(db).check_price_alerts()

    for item in triggered:
        alert: Alert = item["alert"]
        price: float = item["current_price"]
        direction = "이상" if alert.condition == "above" else "이하"
        try:
            await bot.send_message(
                chat_id=settings.TELEGRAM_OWNER_ID,
                text=f"⚠️ 알림 발동!\n{alert.ticker} 현재가 {price:,.2f}\n({direction} {float(alert.price):,.2f})",
            )
        except Exception as e:
            logger.error("알림 발송 실패: %s", e)


async def _build_index_message(title: str) -> str:
    with SessionLocal() as db:
        indices = await MarketService(db).get_all_indices()
    lines = [f"*{title}*\n"]
    for idx in indices:
        sign = "▲" if idx["change_pct"] >= 0 else "▼"
        lines.append(f"{idx['name']}  {idx['close']:,.2f}  {sign}{abs(idx['change_pct']):.2f}%")
    return "\n".join(lines)


async def send_morning_briefing(bot: Bot) -> None:
    try:
        text = await _build_index_message("🌅 모닝 브리핑")
        await bot.send_message(chat_id=settings.TELEGRAM_OWNER_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error("모닝 브리핑 실패: %s", e)


async def send_close_report(bot: Bot) -> None:
    try:
        text = await _build_index_message("📊 장 마감 요약")
        await bot.send_message(chat_id=settings.TELEGRAM_OWNER_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error("마감 요약 실패: %s", e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(refresh_index_cache,   "interval", minutes=15, id="index_refresh")
    scheduler.add_job(check_price_alerts,    "interval", minutes=15, id="alert_check",   args=[bot])
    scheduler.add_job(refresh_rss_feeds,     "interval", minutes=5,  id="rss_refresh")
    scheduler.add_job(translate_news,        "interval", minutes=5,  id="translate_news")
    scheduler.add_job(send_morning_briefing, "cron", hour=9,  minute=0,  id="morning_brief", args=[bot])
    scheduler.add_job(send_close_report,     "cron", hour=15, minute=30, id="close_report",  args=[bot])
    return scheduler
