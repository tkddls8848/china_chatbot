"""Market-aware close-price retrieval with provider-specific fallbacks."""

from __future__ import annotations

import logging
import re
from datetime import date

import akshare as ak
import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_NETWORK_ERRORS = (requests.exceptions.RequestException, ConnectionError, TimeoutError, OSError, ValueError)


def normalize_market(market: str | None, code: str) -> str:
    value = str(market or "").upper().strip()
    if value in {"CN", "SH", "SZ", "STAR", "CHI", "HK", "KR", "US", "JP", "TW", "EU"}:
        return value
    if code.upper().endswith(".KS"):
        return "KR"
    if code.upper().endswith(".T"):
        return "JP"
    if code.upper().endswith(".TW"):
        return "TW"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", code):
        return "US"
    if code.upper().endswith(".HK") or re.fullmatch(r"\d{5}", code):
        return "HK"
    return "CN"


def yahoo_ticker(code: str, market: str) -> str:
    code = code.strip().upper()
    if market == "US" and code.endswith((".N", ".O")):
        return code.rsplit(".", 1)[0]
    if "." in code:
        return code
    if market == "KR":
        return f"{code.zfill(6)}.KS"
    if market == "JP":
        return f"{code.zfill(4)}.T"
    if market == "TW":
        return f"{code.zfill(4)}.TW"
    if market == "HK":
        return f"{code.zfill(4)}.HK"
    if market in {"SH", "CN"} and code.startswith("6"):
        return f"{code.zfill(6)}.SS"
    if market in {"SZ", "CN", "STAR", "CHI"} and re.fullmatch(r"\d{6}", code):
        return f"{code}.SZ"
    return code.replace(".", "-") if market == "US" else code


def _series(frame: pd.DataFrame, date_col: str, close_col: str) -> pd.Series | None:
    if frame is None or frame.empty or date_col not in frame.columns or close_col not in frame.columns:
        return None
    values = pd.Series(pd.to_numeric(frame[close_col], errors="coerce").values, index=pd.to_datetime(frame[date_col], errors="coerce"))
    values = values.dropna().sort_index()
    return values if not values.empty else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), retry=retry_if_exception_type(_NETWORK_ERRORS), reraise=True)
def _akshare_history(code: str, market: str, start: str, end: str) -> pd.Series | None:
    if market == "HK":
        return _series(ak.stock_hk_hist(symbol=code.zfill(5), period="daily", start_date=start, end_date=end, adjust=""), "日期", "收盘")
    return _series(ak.stock_zh_a_hist(symbol=code.zfill(6), period="daily", start_date=start, end_date=end, adjust="qfq"), "日期", "收盘")


def _yahoo_history(ticker: str, start: date, end: date) -> pd.Series | None:
    import yfinance as yf

    frame = yf.download(ticker, start=start.isoformat(), end=date.fromordinal(end.toordinal() + 1).isoformat(), progress=False, auto_adjust=True, threads=False)
    if frame is None or frame.empty:
        return None
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return pd.to_numeric(close, errors="coerce").dropna().sort_index()


def fetch_closes(code: str, market: str | None, start: date, end: date) -> pd.Series | None:
    """Use local-market source first, then Yahoo Finance as an independent fallback."""
    resolved_market = normalize_market(market, code)
    if resolved_market in {"CN", "SH", "SZ", "STAR", "CHI", "HK"}:
        try:
            closes = _akshare_history(code, resolved_market, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if closes is not None:
                return closes
        except Exception as exc:
            logger.warning("[PRICE] AkShare retry exhausted for %s (%s): %s", code, resolved_market, exc)
    try:
        return _yahoo_history(yahoo_ticker(code, resolved_market), start, end)
    except Exception as exc:
        logger.warning("[PRICE] Yahoo fallback failed for %s (%s): %s", code, resolved_market, exc)
        return None
