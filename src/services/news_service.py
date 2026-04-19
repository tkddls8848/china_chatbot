from sqlalchemy.orm import Session

from src.cache import TtlCache
from src.config import settings
from src.data.rss_client import NewsItem, fetch_all_news
from src.db.models.rss_feed import RssFeed
from src.services.translate_service import enrich_with_translations

_cache = TtlCache(settings.CACHE_TTL_SECONDS)
_CACHE_KEY = "rss_news"


def _to_dict(item: NewsItem) -> dict:
    return {
        "title": item.title,
        "link": item.link,
        "published": item.published.isoformat() if item.published else "",
        "source": item.source,
        "source_url": item.source_url,
        "market_tag": item.market_tag,
        "description": item.description,
    }


def _db_feeds(db: Session) -> list[dict]:
    rows = db.query(RssFeed).filter(RssFeed.is_active == True).order_by(RssFeed.id).all()
    return [{"url": r.url, "label": r.label, "market_tag": r.market_tag} for r in rows]


class NewsService:
    def __init__(self, db: Session) -> None:
        self._db = db

    async def get_news(
        self,
        market: str = "all",
        limit: int = 20,
        source: str = "all",
    ) -> list[dict]:
        hit, cached = _cache.get(_CACHE_KEY)
        items: list[dict] = list(cached) if hit else await self._fetch_and_cache()

        if market != "all":
            items = [i for i in items if i.get("market_tag") in (market, "cn", "all")]
        if source != "all":
            items = [i for i in items if i.get("source") == source]

        items = items[:limit]
        enrich_with_translations(self._db, items)
        return items

    async def refresh_cache(self) -> None:
        await self._fetch_and_cache()

    async def _fetch_and_cache(self) -> list[dict]:
        feeds = _db_feeds(self._db)
        raw = await fetch_all_news(feeds=feeds or None, limit=200)
        dicts = [_to_dict(item) for item in raw]
        _cache.set(_CACHE_KEY, dicts)
        return dicts
