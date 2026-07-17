"""Optional Yahoo trial-universe collection and OpenFIGI identifier enrichment."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


def fetch_yahoo_korea_trial(tickers: tuple[str, ...]) -> list[dict[str, Any]]:
    """Collect a bounded Korean ticker trial set from Yahoo Finance metadata."""
    import yfinance as yf
    from yfinance import cache

    cache_dir = Path(__file__).resolve().parents[2] / "data" / "yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.set_cache_location(cache_dir)

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        if not ticker.endswith(".KS"):
            continue
        try:
            info = yf.Ticker(ticker).get_info()
        except Exception as exc:
            logger.warning("[StockDB] Yahoo Korea lookup failed for %s: %s", ticker, exc)
            continue
        symbol = str(info.get("symbol") or ticker).upper()
        rows.append(
            {
                "code": symbol.removesuffix(".KS").zfill(6),
                "ticker": symbol,
                "name": str(info.get("longName") or info.get("shortName") or symbol),
                "exchange": str(info.get("exchange") or "KOSPI"),
                "asset_type": str(info.get("quoteType") or "EQUITY"),
                "currency": str(info.get("currency") or "KRW"),
            }
        )
    return rows


def enrich_openfigi(ticker: str, exchange_code: str, api_key: str = "") -> dict[str, str]:
    """Best-effort FIGI mapping; an unavailable mapping never blocks DB build."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    try:
        response = requests.post(
            "https://api.openfigi.com/v3/mapping",
            headers=headers,
            json=[{"idType": "TICKER", "idValue": ticker, "exchCode": exchange_code}],
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        data = result[0].get("data") if isinstance(result, list) and result else None
        if not data:
            return {}
        match = data[0]
        return {
            key: str(match[key])
            for key in ("figi", "compositeFIGI", "shareClassFIGI")
            if match.get(key)
        }
    except Exception as exc:
        logger.info("[StockDB] OpenFIGI mapping unavailable for %s: %s", ticker, exc)
        return {}
