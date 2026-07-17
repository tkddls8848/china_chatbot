"""On-demand historical news collection for chart-quality sentiment series."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from llm.translator import TranslationService
from news.sources import GlobalArticle, fetch_google_news_history
from state import NewsLog

logger = logging.getLogger(__name__)


def _article_time(article: GlobalArticle, fallback_day: date) -> datetime:
    value = article.published_at.strip()
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.combine(fallback_day, datetime.min.time())


async def backfill_market_history(
    news_log: NewsLog,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    markets: set[str],
    queries: dict[str, str],
    lookback_days: int,
    max_articles_per_day: int = 2,
) -> dict[str, int]:
    """Collect and score missing historical articles without sending Telegram news.

    Fetches each exact calendar day separately, which protects the chart from a
    single current-day point masquerading as a trend.  Existing article IDs are
    skipped, making repeated `/market` requests inexpensive after the first run.
    """
    added = {market: 0 for market in markets}
    today = date.today()
    days = [today - timedelta(days=offset) for offset in range(1, lookback_days + 1)]
    for market in sorted(markets):
        query = queries.get(market)
        if not query:
            logger.warning("[MARKET] no history query configured for %s", market)
            continue
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
