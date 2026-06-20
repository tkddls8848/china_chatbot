"""리서치(시황 분석)용 뉴스 수집기.

관심종목 및 전역 속보에서 분석 입력용 뉴스 아이템을 모은다.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import pandas as pd

from core.config import (
    RESEARCH_NEWS_GLOBAL_LIMIT,
    RESEARCH_NEWS_MAX_ITEMS,
    RESEARCH_NEWS_STOCK_LIMIT_PER_SYMBOL,
)
from news.sources import (
    fetch_cls_raw as _fetch_cls_raw,
    fetch_futu_raw as _fetch_futu_raw,
    fetch_stock_news_raw as _fetch_stock_news_raw,
)
from news.utils import is_timeout_error, translate_article
from llm.translator import TranslationService

logger = logging.getLogger(__name__)


def _row_value(row, candidates: list[str], fallback_index: int | None = None) -> str:
    for key in candidates:
        if key in row.index:
            value = row[key]
            return "" if pd.isna(value) else str(value)
    if fallback_index is not None and fallback_index < len(row.index):
        value = row.iloc[fallback_index]
        return "" if pd.isna(value) else str(value)
    return ""


async def collect_watchlist_news_items(
    watchlist: Dict[str, str],
    limit_per_stock: int = RESEARCH_NEWS_STOCK_LIMIT_PER_SYMBOL,
) -> list[dict[str, str]]:
    news_items: list[dict[str, str]] = []
    cutoff = datetime.now() - timedelta(days=7)

    for code, name in watchlist.items():
        try:
            df = await asyncio.to_thread(_fetch_stock_news_raw, code)
            if df.empty:
                continue

            published_raw = (
                df["发布时间"]
                if "发布时间" in df.columns
                else df.iloc[:, 3]
            )
            published_series = pd.to_datetime(published_raw, errors="coerce")
            df = df[published_series >= cutoff]
            if df.empty:
                continue

            for _, row in df.head(limit_per_stock).iterrows():
                published_at = _row_value(row, ["发布时间"], 3)
                title = _row_value(row, ["新闻标题"], 1)
                content = _row_value(row, ["新闻内容"], 2)
                source = _row_value(row, ["文章来源"], 4) or "Stock"
                url = _row_value(row, ["新闻链接"], 5)
                if not title and not content:
                    continue
                news_items.append(
                    {
                        "id": f"stock:{code}:{published_at}:{title[:20]}",
                        "source": source,
                        "ticker": code,
                        "name": name,
                        "title": title,
                        "content": content[:700],
                        "published_at": published_at,
                        "url": url,
                    }
                )
                if len(news_items) >= RESEARCH_NEWS_MAX_ITEMS:
                    return news_items
        except Exception as e:
            logger.error("[RESEARCH] %s news collection failed: %s", name, e)

    return news_items


def _make_news_item(
    source: str,
    title: str,
    content: str,
    published_at: str,
    url: str = "",
    mentioned_stocks: list[str] | None = None,
    theme_candidates: list[dict[str, Any]] | None = None,
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
    }


async def collect_global_market_news_items(
    translator: TranslationService | None = None,
    translate_semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]]:
    news_items: list[dict[str, Any]] = []

    try:
        df_cls = await asyncio.to_thread(_fetch_cls_raw)
        cls_limit = min(RESEARCH_NEWS_GLOBAL_LIMIT, max(1, RESEARCH_NEWS_MAX_ITEMS // 2))
        for _, row in df_cls.tail(cls_limit).iterrows():
            published_date = _row_value(row, ["发布日期"], 0)
            published_time = _row_value(row, ["发布时间"], 1)
            title = _row_value(row, ["标题"], 2)
            content = _row_value(row, ["内容"], 3)
            if title or content:
                news_items.append(
                    _make_news_item(
                        "CLS",
                        title,
                        content,
                        f"{published_date} {published_time}".strip(),
                    )
                )
    except Exception as e:
        logger.error("[RESEARCH] CLS news collection failed: %s", e)

    try:
        df_futu = await asyncio.to_thread(_fetch_futu_raw)
        futu_limit = min(
            RESEARCH_NEWS_GLOBAL_LIMIT,
            max(1, RESEARCH_NEWS_MAX_ITEMS - len(news_items)),
        )
        for _, row in df_futu.head(futu_limit).iterrows():
            title = _row_value(row, ["标题"], 0)
            content = _row_value(row, ["内容"], 1)
            published_at = _row_value(row, ["发布时间"], 2)
            url = _row_value(row, ["链接"], 3)
            if title or content:
                mentioned_stocks: list[str] = []
                theme_candidates: list[dict[str, Any]] = []
                translated_title = title
                translated_content = content
                if translator is not None and translate_semaphore is not None:
                    try:
                        translated = await translate_article(
                            translator,
                            translate_semaphore,
                            "futu",
                            title,
                            content,
                        )
                        translated_title = translated.title
                        translated_content = translated.content
                        mentioned_stocks = translated.mentioned_stocks
                        theme_candidates = translated.theme_candidates
                    except Exception as e:
                        logger.error("[RESEARCH] Futu translation failed: %s", e)
                        if is_timeout_error(e):
                            break
                        continue
                news_items.append(
                    _make_news_item(
                        "Futu",
                        translated_title,
                        translated_content,
                        published_at,
                        url,
                        mentioned_stocks=mentioned_stocks,
                        theme_candidates=theme_candidates,
                    )
                )
            if len(news_items) >= RESEARCH_NEWS_MAX_ITEMS:
                return news_items
    except Exception as e:
        logger.error("[RESEARCH] Futu news collection failed: %s", e)

    return news_items[:RESEARCH_NEWS_MAX_ITEMS]
