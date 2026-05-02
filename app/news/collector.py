import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from data.models import NewsItem
from news.sources import AkshareClient, XinhuaClient
from settings import Settings

logger = logging.getLogger(__name__)


# ── normalizer helpers ────────────────────────────────────────────────────────

def _row_value(row, candidates: list[str], fallback_index: int | None = None) -> str:
    for key in candidates:
        if key in row.index:
            value = row[key]
            return "" if pd.isna(value) else str(value)
    if fallback_index is not None and fallback_index < len(row.index):
        value = row.iloc[fallback_index]
        return "" if pd.isna(value) else str(value)
    return ""


def _within_news_cutoff(published_at: str, days: int) -> bool:
    if not published_at:
        return False
    try:
        dt = pd.to_datetime(published_at, errors="coerce")
        if pd.isna(dt):
            return False
        cutoff = datetime.now() - timedelta(days=days)
        return dt.to_pydatetime().replace(tzinfo=None) >= cutoff
    except Exception:
        return False


def _make_news_item(
    source: str,
    title: str,
    content: str,
    published_at: str,
    url: str = "",
    ticker: str = "",
    name: str = "",
    max_content: int = 700,
) -> NewsItem:
    return NewsItem(
        id=f"{source}:{ticker}:{published_at}:{title[:30]}",
        source=source,
        ticker=ticker,
        name=name,
        title=title,
        content=content[:max_content],
        published_at=published_at,
        url=url,
    )


def normalize_cls_rows(df, limit: int, days: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for _, row in df.tail(limit).iterrows():
        published_date = _row_value(row, ["发布日期", "发布时间日期", "?묈툋?ζ쐿"], 0)
        published_time = _row_value(row, ["发布时间", "发布时间时间", "?묈툋?띌뿴"], 1)
        published_at = f"{published_date} {published_time}".strip()
        if not _within_news_cutoff(published_at, days):
            continue
        title = _row_value(row, ["标题", "?뉔쥦"], 2)
        content = _row_value(row, ["内容", "?끻?"], 3)
        if title or content:
            items.append(_make_news_item("CLS", title, content, published_at))
    return items


def normalize_futu_rows(df, limit: int, days: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for _, row in df.head(limit).iterrows():
        published_at = _row_value(row, ["发布时间", "发布时间时间", "?묈툋?띌뿴"], 2)
        if not _within_news_cutoff(published_at, days):
            continue
        title = _row_value(row, ["标题", "?뉔쥦"], 0)
        content = _row_value(row, ["内容", "?끻?"], 1)
        url = _row_value(row, ["链接", "?얏렏"], 3)
        if title or content:
            items.append(_make_news_item("Futu", title, content, published_at, url))
    return items


def normalize_stock_news_rows(
    code: str,
    name: str,
    df,
    limit: int,
    days: int,
) -> list[NewsItem]:
    if df.empty:
        return []
    published_raw = df["发布时间"] if "发布时间" in df.columns else df.iloc[:, 3]
    published_series = pd.to_datetime(published_raw, errors="coerce")
    cutoff = datetime.now() - timedelta(days=days)
    filtered = df[published_series >= cutoff]

    items: list[NewsItem] = []
    for _, row in filtered.head(limit).iterrows():
        published_at = _row_value(row, ["发布时间", "?묈툋?띌뿴"], 3)
        title = _row_value(row, ["新闻标题", "?곈뿻?뉔쥦"], 1)
        content = _row_value(row, ["新闻内容", "?곈뿻?끻?"], 2)
        source = _row_value(row, ["文章来源", "?뉒쳽?ζ틦"], 4) or "Stock"
        url = _row_value(row, ["新闻链接", "?곈뿻?얏렏"], 5)
        if title or content:
            items.append(
                _make_news_item(source, title, content, published_at, url, code, name)
            )
    return items


def normalize_xinhua_entries(entries: list[dict[str, Any]], limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for entry in entries[:limit]:
        title = str(entry.get("title") or "").strip()
        content = str(entry.get("content") or "").strip()
        published = str(entry.get("published") or "")
        link = str(entry.get("link") or "")
        if title:
            items.append(_make_news_item("Xinhua", title, content, published, link))
    return items


# ── NewsCollector ─────────────────────────────────────────────────────────────

class NewsCollector:
    def __init__(
        self,
        settings: Settings,
        akshare_client: AkshareClient,
        xinhua_client: XinhuaClient,
    ):
        self._settings = settings
        self._akshare = akshare_client
        self._xinhua = xinhua_client

    async def collect_global_market_news(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            df_cls = await asyncio.to_thread(self._akshare.fetch_cls_raw)
            items.extend(
                normalize_cls_rows(
                    df_cls,
                    self._settings.view_global_news_limit,
                    self._settings.view_news_days,
                )
            )
        except Exception as e:
            logger.error("[VIEW] CLS news collection failed: %s", e)

        try:
            df_futu = await asyncio.to_thread(self._akshare.fetch_futu_raw)
            items.extend(
                normalize_futu_rows(
                    df_futu,
                    self._settings.view_global_news_limit,
                    self._settings.view_news_days,
                )
            )
        except Exception as e:
            logger.error("[VIEW] Futu news collection failed: %s", e)

        return items[: self._settings.view_max_news_items]

    async def collect_watchlist_news(self, watchlist: dict[str, str]) -> list[NewsItem]:
        items: list[NewsItem] = []
        for code, name in watchlist.items():
            try:
                df = await asyncio.to_thread(self._akshare.fetch_stock_news_raw, code)
                items.extend(
                    normalize_stock_news_rows(
                        code,
                        name,
                        df,
                        self._settings.view_news_limit_per_stock,
                        self._settings.view_news_days,
                    )
                )
                if len(items) >= self._settings.view_max_news_items:
                    break
            except Exception as e:
                logger.error("[VIEW] %s news collection failed: %s", name, e)
        return items[: self._settings.view_max_news_items]

    async def collect_xinhua_news(self) -> list[NewsItem]:
        if not self._settings.xinhua_enabled:
            return []
        entries = await asyncio.to_thread(self._xinhua.fetch_entries)
        return normalize_xinhua_entries(entries, self._settings.xinhua_news_limit)
