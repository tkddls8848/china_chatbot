"""리서치(시황 분석)용 뉴스 수집기.

전역 속보에서 분석 입력용 뉴스 아이템을 모은다. 뉴스 파이프라인과 동일한
NewsSourceRegistry를 공유해 소스 페일오버를 그대로 따른다.
"""

import asyncio
import logging
from typing import Any

from core.config import (
    NEWS_LIVE_MAX_AGE_HOURS,
    NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    RESEARCH_NEWS_GLOBAL_LIMIT,
    RESEARCH_NEWS_MAX_ITEMS,
)
from news.registry import NewsSourceRegistry
from news.utils import (
    filter_recent_articles,
    is_timeout_error,
    translate_article,
)
from llm.translator import TranslationService

logger = logging.getLogger(__name__)


async def _fetch_source(func, *args):
    return await asyncio.wait_for(
        asyncio.to_thread(func, *args),
        timeout=NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    )


def _make_news_item(
    source: str,
    title: str,
    content: str,
    published_at: str,
    url: str = "",
    mentioned_stocks: list[str] | None = None,
    theme_candidates: list[dict[str, Any]] | None = None,
    sentiment: float | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{source}:{published_at}:{title[:30]}",
        "source": source,
        "ticker": "",
        "name": "",
        "title": title[:240],
        "content": content[:700],
        "published_at": published_at,
        "url": url,
        "mentioned_stocks": mentioned_stocks or [],
        "theme_candidates": theme_candidates or [],
        "sentiment": sentiment,
    }


async def collect_global_market_news_items(
    translator: TranslationService | None = None,
    translate_semaphore: asyncio.Semaphore | None = None,
    registry: NewsSourceRegistry | None = None,
    max_items: int = RESEARCH_NEWS_MAX_ITEMS,
) -> list[dict[str, Any]]:
    """레지스트리의 활성 소스에서 최신 뉴스를 모아 분석 입력으로 변환한다."""
    if registry is None:
        logger.warning("[RESEARCH] news registry가 없어 전역 뉴스 수집을 건너뜁니다.")
        return []

    news_items: list[dict[str, Any]] = []
    for spec in registry.active_specs():
        if len(news_items) >= max_items:
            break
        try:
            articles = await _fetch_source(spec.fetch)
            registry.record_success(spec.key)
        except TimeoutError:
            registry.record_failure(spec.key, "timeout")
            logger.error(
                "[RESEARCH] %s news collection timed out: %.1f seconds",
                spec.key,
                NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
            )
            continue
        except Exception as e:
            registry.record_failure(spec.key, str(e))
            logger.error("[RESEARCH] %s news collection failed: %s", spec.key, e)
            continue

        articles = filter_recent_articles(articles, NEWS_LIVE_MAX_AGE_HOURS)
        source_limit = min(RESEARCH_NEWS_GLOBAL_LIMIT, max_items - len(news_items))
        for article in articles[:source_limit]:
            title = article.title
            content = article.content
            mentioned_stocks: list[str] = []
            theme_candidates: list[dict[str, Any]] = []
            sentiment: float | None = None
            if translator is not None and translate_semaphore is not None:
                try:
                    translated = await translate_article(
                        translator,
                        translate_semaphore,
                        spec.prompt_key,
                        title,
                        content,
                    )
                    title = translated.title
                    content = translated.content
                    mentioned_stocks = translated.mentioned_stocks
                    theme_candidates = translated.theme_candidates
                    sentiment = translated.sentiment
                except Exception as e:
                    logger.error("[RESEARCH] %s translation failed: %s", spec.key, e)
                    if is_timeout_error(e):
                        return news_items[:max_items]
                    continue
            news_items.append(
                _make_news_item(
                    spec.label,
                    title,
                    content,
                    article.published_at,
                    article.url,
                    mentioned_stocks=mentioned_stocks,
                    theme_candidates=theme_candidates,
                    sentiment=sentiment,
                )
            )
            if len(news_items) >= max_items:
                break

    return news_items[:max_items]
