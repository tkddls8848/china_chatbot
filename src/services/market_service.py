import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.config import settings
from src.data.akshare_client import AkshareClient
from src.data.yfinance_client import YfinanceClient

_cache: dict = {}


class MarketService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()
        self._yf = YfinanceClient()

    def _fresh(self, key: str) -> bool:
        entry = _cache.get(key)
        if not entry:
            return False
        age = (datetime.now(timezone.utc) - entry["ts"]).total_seconds()
        return age < settings.CACHE_TTL_SECONDS

    def _set(self, key: str, data: object) -> None:
        _cache[key] = {"ts": datetime.now(timezone.utc), "data": data}

    def _get(self, key: str) -> object:
        return _cache[key]["data"]

    async def get_all_indices(self) -> list[dict]:
        key = "all_indices"
        if self._fresh(key):
            return self._get(key)  # type: ignore[return-value]
        ak_data = await self._ak.get_all_index_spots()
        hk_tasks = [self._yf.get_index_spot("hk"), self._yf.get_index_spot("hk_tech")]
        hk_results = await asyncio.gather(*hk_tasks, return_exceptions=True)
        hk_data = [r for r in hk_results if isinstance(r, dict)]
        result = ak_data + hk_data
        self._set(key, result)
        return result

    async def get_index(self, market_id: str) -> dict:
        if market_id in ("hk", "hk_tech"):
            return await self._yf.get_index_spot(market_id)
        return await self._ak.get_index_spot(market_id)

    async def get_top_stocks(self, market_id: str, limit: int = 20) -> list[dict]:
        df = await self._ak.get_stock_spot()
        return df.head(limit).to_dict(orient="records")

    async def get_sector_changes(self) -> list[dict]:
        return await self._ak.get_sector_changes()
