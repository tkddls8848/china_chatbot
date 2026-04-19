from sqlalchemy.orm import Session

from src.data.akshare_client import AkshareClient
from src.data.yfinance_client import YfinanceClient


class StockService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()
        self._yf = YfinanceClient()

    async def search(self, query: str) -> list[dict]:
        return await self._ak.search_stocks(query)

    async def get_info(self, ticker: str) -> dict:
        if ticker.upper().endswith(".HK"):
            return await self._yf.get_ticker_info(ticker)
        return await self._ak.get_stock_info(ticker)

    async def get_chart(self, ticker: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        return await self._yf.get_ticker_history(ticker, period=period, interval=interval)

    async def get_news(self, ticker: str, limit: int = 20) -> list[dict]:
        return await self._ak.get_stock_news(ticker, limit=limit)
