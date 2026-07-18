"""On-demand historical news collection for chart-quality sentiment series."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from llm.translator import TranslationService
from news.sources import GlobalArticle, fetch_google_news_history
from state import NewsLog

logger = logging.getLogger(__name__)


def _article_time(article: GlobalArticle, fallback_day: date) -> datetime:
    del article
    return datetime.combine(fallback_day, datetime.max.time()).replace(microsecond=0)


async def backfill_market_history(
    news_log: NewsLog,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    markets: set[str],
    queries: dict[str, str],
    lookback_days: int,
    max_articles_per_day: int = 2,
    days_by_market: dict[str, list[date]] | None = None,
) -> dict[str, int]:
    """Collect and score missing historical articles without sending Telegram news.

    Fetches each exact calendar day separately, which protects the chart from a
    single current-day point masquerading as a trend.  Existing article IDs are
    skipped, making repeated `/market` requests inexpensive after the first run.
    """
    added = {market: 0 for market in markets}
    today = date.today()
    default_days = [
        today - timedelta(days=offset)
        for offset in range(1, lookback_days + 1)
    ]
    for market in sorted(markets):
        query = queries.get(market)
        if not query:
            logger.warning("[MARKET] no history query configured for %s", market)
            continue
        days = (
            days_by_market.get(market, [])
            if days_by_market is not None
            else default_days
        )
        for day in days:
            try:
                articles = await asyncio.to_thread(fetch_google_news_history, query, day, market)
            except Exception as exc:
                logger.warning("[MARKET] historical fetch failed for %s %s: %s", market, day, exc)
                continue
            for article in articles[:max_articles_per_day]:
                source = f"history:{market}"
                article_id = f"history:{market}:{article.article_id}"
                if await news_log.contains_article(article_id):
                    continue
                try:
                    async with translate_semaphore:
                        translated = await asyncio.to_thread(
                            translator.translate_article,
                            "global",
                            article.title,
                            article.content,
                        )
                    if translated.sentiment is None:
                        continue
                    if await news_log.record(
                        source=source,
                        title=translated.title,
                        sentiment=translated.sentiment,
                        impact=translated.impact,
                        codes=[],
                        market=market,
                        article_id=article_id,
                        occurred_at=_article_time(article, day),
                    ):
                        added[market] += 1
                except Exception as exc:
                    logger.warning("[MARKET] historical sentiment failed for %s %s: %s", market, day, exc)
    return added
