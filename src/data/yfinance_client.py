import asyncio
from functools import partial
from typing import Any

import yfinance as yf

from src.exceptions import DataFetchError

HK_SYMBOLS: dict[str, str] = {
    "hk": "^HSI",
    "hk_tech": "^HSTECH",
}

HK_NAMES: dict[str, str] = {
    "hk": "홍콩 항셍",
    "hk_tech": "홍콩 항셍테크",
}


class YfinanceClient:
    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, partial(func, *args, **kwargs))
        except Exception as e:
            raise DataFetchError(str(e)) from e

    async def get_index_spot(self, market_id: str) -> dict:
        symbol = HK_SYMBOLS.get(market_id)
        if not symbol:
            raise DataFetchError(f"Unknown HK market_id: {market_id}")
        ticker = yf.Ticker(symbol)
        hist = await self._run(ticker.history, period="5d", auto_adjust=True)
        if hist.empty:
            raise DataFetchError(f"No data for {symbol}")
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        close = float(latest["Close"])
        prev_close = float(prev["Close"])
        change = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        return {
            "market_id": market_id,
            "name": HK_NAMES.get(market_id, market_id),
            "symbol": symbol,
            "date": str(latest.name.date()),
            "close": round(close, 2),
            "open": round(float(latest["Open"]), 2),
            "high": round(float(latest["High"]), 2),
            "low": round(float(latest["Low"]), 2),
            "volume": int(latest.get("Volume", 0)),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }

    async def get_ticker_info(self, symbol: str) -> dict:
        ticker = yf.Ticker(symbol)
        return await self._run(lambda: ticker.info)

    async def get_ticker_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        ticker = yf.Ticker(symbol)
        hist = await self._run(ticker.history, period=period, interval=interval)
        records = []
        for ts, row in hist.iterrows():
            records.append({
                "date": str(ts.date()),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return records
