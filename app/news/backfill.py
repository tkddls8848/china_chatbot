"""On-demand historical news collection for chart-quality sentiment series."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from llm.translator import TranslationService
from news.sources import GlobalArticle, fetch_google_news_history
from news.utils import filter_articles_for_kst_day, publication_time_naive
from state import NewsLog

logger = logging.getLogger(__name__)


def _article_time(article: GlobalArticle, target_day: date) -> datetime | None:
    published_at = publication_time_naive(
        article.published_at,
        article.published_date or None,
    )
    if published_at is None or published_at.date() != target_day:
        return None
    return published_at


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
        for offset in range(max(1, lookback_days))
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
            articles = filter_articles_for_kst_day(articles, day)
            for article in articles[:max_articles_per_day]:
                source = f"history:{market}"
                article_id = f"history:{market}:{article.article_id}"
                if await news_log.contains_article(article_id):
                    continue
                occurred_at = _article_time(article, day)
                if occurred_at is None:
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
                        occurred_at=occurred_at,
                    ):
                        added[market] += 1
                except Exception as exc:
                    logger.warning("[MARKET] historical sentiment failed for %s %s: %s", market, day, exc)
    return added
