import asyncio
import dataclasses
from datetime import datetime
from typing import Optional

import feedparser
import httpx

from src.config import settings


@dataclasses.dataclass
class NewsItem:
    title: str
    link: str
    published: Optional[datetime]
    source: str        # 레이블 (e.g. "财联社전보")
    source_url: str    # RSSHub 라우트 URL
    market_tag: str    # "cn" | "hk" | "global"
    description: str = ""


def _infer_market(url: str) -> str:
    if any(k in url for k in ("scmp", "hkej")):
        return "hk"
    if "reuters" in url:
        return "global"
    return "cn"


def _build_registry() -> list[dict]:
    urls = [u.strip() for u in settings.RSS_FEED_URLS.split(",") if u.strip()]
    labels = [l.strip() for l in settings.RSS_SOURCE_LABELS.split(",") if l.strip()]
    registry = []
    for i, url in enumerate(urls):
        label = labels[i] if i < len(labels) else url
        registry.append({
            "url": url,
            "label": label,
            "market_tag": _infer_market(url),
        })
    return registry


_feed_registry: list[dict] = _build_registry()


def list_feeds() -> list[dict]:
    return list(_feed_registry)


def add_feed(url: str, label: str, market_tag: str = "cn") -> bool:
    if any(f["url"] == url for f in _feed_registry):
        return False
    _feed_registry.append({"url": url, "label": label, "market_tag": market_tag})
    return True


def remove_feed(url: str) -> bool:
    global _feed_registry
    before = len(_feed_registry)
    _feed_registry = [f for f in _feed_registry if f["url"] != url]
    return len(_feed_registry) < before


async def _fetch_feed(client: httpx.AsyncClient, feed: dict) -> list[NewsItem]:
    try:
        resp = await client.get(feed["url"], timeout=settings.RSS_FETCH_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []

    items = []
    for entry in feedparser.parse(resp.text).entries[: settings.RSS_MAX_ITEMS_PER_FEED]:
        published: Optional[datetime] = None
        if getattr(entry, "published_parsed", None):
            try:
                published = datetime(*entry.published_parsed[:6])
            except Exception:
                pass
        items.append(NewsItem(
            title=entry.get("title", "").strip(),
            link=entry.get("link", ""),
            published=published,
            source=feed["label"],
            source_url=feed["url"],
            market_tag=feed["market_tag"],
            description=entry.get("summary", "").strip(),
        ))
    return items


async def fetch_all_news(feeds: list[dict] | None = None, limit: int = 200) -> list[NewsItem]:
    active_feeds = feeds if feeds is not None else list(_feed_registry)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        batches = await asyncio.gather(*[_fetch_feed(client, f) for f in active_feeds])

    seen: set[str] = set()
    merged: list[NewsItem] = []
    for batch in batches:
        for item in batch:
            if item.link and item.link not in seen:
                seen.add(item.link)
                merged.append(item)

    merged.sort(key=lambda x: x.published or datetime.min, reverse=True)
    return merged[:limit]
