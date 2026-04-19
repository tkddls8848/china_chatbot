import asyncio
from functools import partial

import akshare as ak
from sqlalchemy.orm import Session

from src.data.akshare_client import AkshareClient
from src.exceptions import DataFetchError

# akshare는 중국 A주 뉴스만 제공 — 홍콩은 일반 재경 뉴스로 대체
MARKET_SYMBOL_MAP: dict[str, str] = {
    "sh_main": "000001",
    "sz_main": "399001",
    "star": "000688",
    "chinext": "399006",
    "all": "000001",
}


class NewsService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()

    async def get_news(self, market: str = "all", limit: int = 20) -> list[dict]:
        if market == "hk":
            return await self._get_finance_news(limit)
        symbol = MARKET_SYMBOL_MAP.get(market, "000001")
        return await self._ak.get_stock_news(symbol, limit=limit)

    async def _get_finance_news(self, limit: int) -> list[dict]:
        loop = asyncio.get_event_loop()
        try:
            df = await loop.run_in_executor(None, partial(ak.stock_news_em, symbol="000001"))
            return df.head(limit).to_dict(orient="records")
        except Exception as e:
            raise DataFetchError(str(e)) from e
