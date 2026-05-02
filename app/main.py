import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.store import MarketViewManager, SentNewsTracker, WatchlistManager
from data.stock_db import StockDatabase
from handlers.core import build_telegram_app
from llm.analyzer import MarketViewAnalyzer
from llm.translator import TranslationService
from news.collector import NewsCollector
from news.sender import _refresh_stock_db, fetch_all
from news.sources import AkshareClient, XinhuaClient
from settings import Settings
from view.market_view import (
    CandidateService,
    MarketViewAnalysisService,
    MarketViewFormatter,
    ViewActionPolicy,
    ViewActionService,
    ViewPendingStore,
)


@dataclass
class AppServices:
    settings: Settings
    sent_tracker: SentNewsTracker
    watchlist: WatchlistManager
    market_view_store: MarketViewManager
    pending_store: ViewPendingStore
    stock_db: StockDatabase
    translator: TranslationService
    translate_semaphore: asyncio.Semaphore
    akshare_client: AkshareClient
    xinhua_client: XinhuaClient
    news_collector: NewsCollector
    market_view_analyzer: MarketViewAnalyzer
    market_view_analysis: MarketViewAnalysisService
    view_actions: ViewActionService


def build_services(settings: Settings) -> AppServices:
    stock_db = StockDatabase(
        cache_file=settings.stock_db_file,
        enabled=settings.stock_db_enabled,
    )
    stock_db.load_or_build()

    sent_tracker = SentNewsTracker(settings.sent_ids_file)
    watchlist = WatchlistManager(settings.watchlist_file)
    market_view_store = MarketViewManager(settings.market_view_file)
    pending_store = ViewPendingStore(settings)

    translator = TranslationService(
        base_url=settings.ollama_base_url,
        model=settings.translate_model,
        enabled=settings.translate_enabled,
        timeout=settings.translate_timeout,
        prompt_dir=settings.prompt_dir,
        fallback_to_original=settings.translate_fallback_to_original,
        num_gpu=settings.ollama_num_gpu,
        num_predict=settings.translate_num_predict,
    )
    translate_semaphore = asyncio.Semaphore(settings.translate_concurrency)

    akshare_client = AkshareClient()
    xinhua_client = XinhuaClient(settings.xinhua_feeds)
    news_collector = NewsCollector(settings, akshare_client, xinhua_client)

    market_view_analyzer = MarketViewAnalyzer(
        base_url=settings.ollama_base_url,
        model=settings.market_view_model,
        enabled=settings.market_view_enabled,
        timeout=settings.market_view_timeout,
        num_predict=settings.market_view_num_predict,
        prompt_file=settings.market_view_prompt_file,
        num_gpu=settings.ollama_num_gpu,
    )

    candidate_service = CandidateService(settings, stock_db)
    action_policy = ViewActionPolicy(settings, stock_db)
    formatter = MarketViewFormatter(settings)
    market_view_analysis = MarketViewAnalysisService(
        watchlist=watchlist,
        market_view_store=market_view_store,
        analyzer=market_view_analyzer,
        news_collector=news_collector,
        candidate_service=candidate_service,
        action_policy=action_policy,
        pending_store=pending_store,
        formatter=formatter,
    )
    view_actions = ViewActionService(watchlist, stock_db, translator, pending_store)

    return AppServices(
        settings=settings,
        sent_tracker=sent_tracker,
        watchlist=watchlist,
        market_view_store=market_view_store,
        pending_store=pending_store,
        stock_db=stock_db,
        translator=translator,
        translate_semaphore=translate_semaphore,
        akshare_client=akshare_client,
        xinhua_client=xinhua_client,
        news_collector=news_collector,
        market_view_analyzer=market_view_analyzer,
        market_view_analysis=market_view_analysis,
        view_actions=view_actions,
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    services = build_services(settings)
    app = build_telegram_app(services)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        fetch_all,
        trigger="interval",
        minutes=settings.schedule_interval_minutes,
        args=[app],
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _refresh_stock_db,
        trigger="cron",
        hour=8,
        minute=30,
        args=[services.stock_db],
        id="refresh_stock_db",
    )
    scheduler.start()
    logging.getLogger(__name__).info(
        "bot started. commands: /start /help /menu /add /list /view"
    )
    app.run_polling()


if __name__ == "__main__":
    main()
