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

_CN_TAGS = {"CN", "SH", "SZ", "STAR", "CHI"}
_MARKETS = {"CN", "SH", "SZ", "STAR", "CHI", "HK", "KR", "US", "JP", "TW", "EU"}
# 본토 A주 6자리 코드: 상하이 6xxxxx, 선전 000~003·300/301.
_A_SHARE_RE = re.compile(r"6\d{5}|(?:00[0-3]|30[01])\d{3}")


def normalize_market(market: str | None, code: str) -> str:
    value = str(market or "").upper().strip()
    raw = code.upper().strip()
    # 리서치 로그가 홍콩(5자리)·한국 종목을 CN 계열로 잘못 태깅하는 경우가 있다.
    # CN 계열 태그는 코드가 실제 A주 형식일 때만 신뢰하고, 어긋나면 태그를 버려
    # 형식 기반으로 재추론한다(죽은 SH/SZ 티커를 만들어 404를 반복하지 않도록).
    if value in _CN_TAGS and not _A_SHARE_RE.fullmatch(raw):
        value = ""
    if value in _MARKETS:
        return value
    if raw.endswith(".KS"):
        return "KR"
    if raw.endswith(".T"):
        return "JP"
    if raw.endswith(".TW"):
        return "TW"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", code):
        return "US"
    if raw.endswith(".HK") or re.fullmatch(r"\d{5}", raw):
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
    if market in {"SH", "CN"} and re.fullmatch(r"6\d{5}", code):
        return f"{code}.SS"
    if market in {"SZ", "CN", "STAR", "CHI"} and re.fullmatch(r"(?:00[0-3]|30[01])\d{3}", code):
        return f"{code}.SZ"
    if market == "US":
        return code.replace(".", "-")
    # 접미사를 붙일 수 없는 조합(예: CN 태그가 붙은 한국 6자리 코드)은
    # 빈 문자열을 반환해 무의미한 Yahoo 404 호출을 건너뛴다.
    return ""


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
    normalized_code = code.strip().upper()
    # A주가 아닌 잘못 태깅된 코드로 AkShare를 두드리면 동방재부가 연결을 끊어
    # RemoteDisconnected 재시도만 반복된다. HK 또는 실제 A주일 때만 호출한다.
    use_akshare = resolved_market == "HK" or (
        resolved_market in _CN_TAGS and _A_SHARE_RE.fullmatch(normalized_code) is not None
    )
    if use_akshare:
        try:
            closes = _akshare_history(code, resolved_market, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if closes is not None:
                return closes
        except Exception as exc:
            logger.warning("[PRICE] AkShare retry exhausted for %s (%s): %s", code, resolved_market, exc)
    ticker = yahoo_ticker(code, resolved_market)
    if not ticker:
        logger.warning("[PRICE] Yahoo 티커를 해석할 수 없어 건너뜁니다: %s (%s)", code, resolved_market)
        return None
    try:
        return _yahoo_history(ticker, start, end)
    except Exception as exc:
        logger.warning("[PRICE] Yahoo fallback failed for %s (%s): %s", code, resolved_market, exc)
        return None
