import asyncio

from sqlalchemy.orm import Session

from src.cache import TtlCache
from src.config import settings
from src.data.akshare_client import AkshareClient
from src.data.yfinance_client import YfinanceClient

_cache = TtlCache(settings.CACHE_TTL_SECONDS)


class MarketService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()
        self._yf = YfinanceClient()

    async def get_all_indices(self) -> list[dict]:
        hit, data = _cache.get("all_indices")
        if hit:
            return data
        ak_data = await self._ak.get_all_index_spots()
        hk_results = await asyncio.gather(
            self._yf.get_index_spot("hk"),
            self._yf.get_index_spot("hk_tech"),
            return_exceptions=True,
        )
        hk_data = [r for r in hk_results if isinstance(r, dict)]
        result = ak_data + hk_data
        _cache.set("all_indices", result)
        return result

    async def get_index(self, market_id: str) -> dict:
        key = f"index_{market_id}"
        hit, data = _cache.get(key)
        if hit:
            return data
        if market_id in ("hk", "hk_tech"):
            result = await self._yf.get_index_spot(market_id)
        else:
            result = await self._ak.get_index_spot(market_id)
        _cache.set(key, result)
        return result

    async def get_top_stocks(self, market_id: str, limit: int = 20) -> list[dict]:
        key = f"top_{market_id}_{limit}"
        hit, data = _cache.get(key)
        if hit:
            return data
        df = await self._ak.get_stock_spot()
        result = df.head(limit).to_dict(orient="records")
        _cache.set(key, result)
        return result

    async def get_sector_changes(self) -> list[dict]:
        hit, data = _cache.get("sectors")
        if hit:
            return data
        result = await self._ak.get_sector_changes()
        _cache.set("sectors", result)
        return result

    def cache_info(self) -> dict:
        return _cache.info()
