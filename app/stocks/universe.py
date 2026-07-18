"""Country-specific listed-stock universe collectors."""

from __future__ import annotations

import csv
import io

import requests

NASDAQ_DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def stock_key(market: str, exchange: str, code: str) -> str:
    return f"{market.upper()}:{exchange.upper()}:{code.strip().upper()}"


def parse_nasdaq_directory(text: str, exchange: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = str(row.get("Symbol") or "").strip().upper()
        if not symbol or symbol.startswith("File Creation Time"):
            continue
        if str(row.get("Test Issue") or "N").upper() == "Y" or str(row.get("ETF") or "N").upper() == "Y":
            continue
        name = str(row.get("Security Name") or "").strip()
        if not name:
            continue
        resolved_exchange = str(row.get("Exchange") or exchange).strip().upper()
        rows.append({"key": stock_key("US", resolved_exchange, symbol), "code": symbol, "display_name": name, "market": "US", "exchange": resolved_exchange, "yahoo_ticker": symbol})
    return rows


def fetch_us_listed() -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for url, exchange in ((NASDAQ_DIRECTORY_URL, "NASDAQ"), (OTHER_DIRECTORY_URL, "NYSE")):
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        for row in parse_nasdaq_directory(response.text, exchange):
            result[row["key"]] = row
    return list(result.values())


def fetch_kr_listed() -> list[dict[str, str]]:
    import FinanceDataReader as fdr

    frame = fdr.StockListing("KRX")
    rows: list[dict[str, str]] = []
    for _, item in frame.iterrows():
        raw_exchange = str(item.get("Market") or "").upper()
        if raw_exchange not in {"KOSPI", "KOSDAQ", "KONEX"}:
            continue
        code = str(item.get("Code") or "").zfill(6)
        name = str(item.get("Name") or "").strip()
        if not code.isdigit() or not name:
            continue
        rows.append({"key": stock_key("KR", raw_exchange, code), "code": code, "display_name": name, "market": "KR", "exchange": raw_exchange, "yahoo_ticker": f"{code}.KS" if raw_exchange == "KOSPI" else f"{code}.KQ"})
    return rows
