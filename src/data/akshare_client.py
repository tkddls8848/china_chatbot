import asyncio
import os
from functools import partial
from typing import Any

os.environ.setdefault("TQDM_DISABLE", "1")

import akshare as ak
import pandas as pd

from src.cache import TtlCache
from src.config import settings
from src.exceptions import DataFetchError

MARKET_INDEX_MAP: dict[str, str] = {
    "sh_main": "sh000001",
    "sz_main": "sz399001",
    "star": "sh000688",
    "chinext": "sz399006",
}

MARKET_NAMES: dict[str, str] = {
    "sh_main": "상해 메인보드",
    "sz_main": "선전 메인보드",
    "star": "과창판(STAR)",
    "chinext": "창업판(ChiNext)",
}

# 전체 A주 종목 스냅샷 — 가장 비싼 호출(58페이지)이므로 모듈 단위 캐시
_spot_cache: TtlCache = TtlCache(settings.CACHE_TTL_SECONDS)
_info_cache: TtlCache = TtlCache(settings.CACHE_TTL_SECONDS)


class AkshareClient:
    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, partial(func, *args, **kwargs))
        except Exception as e:
            raise DataFetchError(str(e)) from e

    async def get_index_spot(self, market_id: str) -> dict:
        symbol = MARKET_INDEX_MAP.get(market_id)
        if not symbol:
            raise DataFetchError(f"Unknown market_id: {market_id}")
        df: pd.DataFrame = await self._run(ak.stock_zh_index_daily, symbol=symbol)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        change = float(latest["close"]) - float(prev["close"])
        change_pct = change / float(prev["close"]) * 100
        return {
            "market_id": market_id,
            "name": MARKET_NAMES.get(market_id, market_id),
            "symbol": symbol,
            "date": str(latest["date"]),
            "close": round(float(latest["close"]), 2),
            "open": round(float(latest["open"]), 2),
            "high": round(float(latest["high"]), 2),
            "low": round(float(latest["low"]), 2),
            "volume": float(latest.get("volume", 0)),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }

    async def get_all_index_spots(self) -> list[dict]:
        tasks = [self.get_index_spot(m) for m in MARKET_INDEX_MAP]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    async def get_stock_spot(self) -> pd.DataFrame:
        hit, data = _spot_cache.get("spot")
        if hit:
            return data
        df: pd.DataFrame = await self._run(ak.stock_zh_a_spot_em)
        _spot_cache.set("spot", df)
        return df

    async def get_stock_info(self, symbol: str) -> dict:
        hit, data = _info_cache.get(symbol)
        if hit:
            return data
        df: pd.DataFrame = await self._run(ak.stock_individual_info_em, symbol=symbol)
        result = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        _info_cache.set(symbol, result)
        return result

    async def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        df: pd.DataFrame = await self._run(ak.stock_news_em, symbol=symbol)
        return df.head(limit).to_dict(orient="records")

    async def get_sector_changes(self) -> list[dict]:
        df: pd.DataFrame = await self._run(ak.stock_board_industry_name_em)
        return df.head(30).to_dict(orient="records")

    async def search_stocks(self, query: str) -> list[dict]:
        df: pd.DataFrame = await self.get_stock_spot()
        mask = df["名称"].str.contains(query, na=False) | df["代码"].str.contains(query, na=False)
        return df[mask].head(20).to_dict(orient="records")
