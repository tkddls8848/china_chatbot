import logging

from telegram.ext import Application, CommandHandler

from src.bot.handlers.alert import alert_list
from src.bot.handlers.market import market
from src.bot.handlers.news import news
from src.bot.handlers.start import start
from src.config import settings
from src.db.session import create_tables
from src.scheduler.jobs import setup_scheduler, translate_news

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=settings.LOG_LEVEL,
)


def main() -> None:
    create_tables()

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("news",   news))
    app.add_handler(CommandHandler("alert",  alert_list))

    scheduler = setup_scheduler(app.bot)
    scheduler.add_job(translate_news, "date", id="translate_on_start")
    scheduler.start()

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
