from sqlalchemy.orm import Session

from src.cache import TtlCache
from src.config import settings
from src.data.akshare_client import AkshareClient
from src.data.yfinance_client import YfinanceClient

_chart_cache = TtlCache(settings.CACHE_TTL_SECONDS)


class StockService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()
        self._yf = YfinanceClient()

    async def search(self, query: str) -> list[dict]:
        # get_stock_spot() 자체가 akshare_client에서 캐싱됨
        return await self._ak.search_stocks(query)

    async def get_info(self, ticker: str) -> dict:
        # get_stock_info() 자체가 akshare_client에서 캐싱됨
        if ticker.upper().endswith(".HK"):
            return await self._yf.get_ticker_info(ticker)
        return await self._ak.get_stock_info(ticker)

    async def get_chart(self, ticker: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        key = f"chart_{ticker}_{period}_{interval}"
        hit, data = _chart_cache.get(key)
        if hit:
            return data
        result = await self._yf.get_ticker_history(ticker, period=period, interval=interval)
        _chart_cache.set(key, result)
        return result

    async def get_news(self, ticker: str, limit: int = 20) -> list[dict]:
        return await self._ak.get_stock_news(ticker, limit=limit)
