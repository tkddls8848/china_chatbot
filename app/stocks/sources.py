"""종목 DB 구축에 필요한 원본 목록과 이름 정규화 도구."""

import logging
import re
from http.client import RemoteDisconnected
from typing import Any, Callable

import akshare as ak
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

try:
    import hanja
except ImportError:
    hanja = None

try:
    from opencc import OpenCC
except ImportError:
    OpenCC = None

_OPENCC_S2T = None
NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
    RemoteDisconnected,
)


def _retry_on_network(func: Callable):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(NETWORK_ERRORS),
        reraise=True,
    )(func)


@_retry_on_network
def _fetch_a_code_name():
    return ak.stock_info_a_code_name()


@_retry_on_network
def _fetch_hk_spot():
    return ak.stock_hk_spot()


def _classify_market(code: str) -> str:
    if len(code) <= 5:
        return "HK"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("300", "301")):
        return "CHI"
    return "SH" if code.startswith("6") else "SZ"


def _clean_stock_name(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return re.sub(r"\s+", " ", str(value)).strip()


def _to_traditional_chinese(text: str) -> str:
    global _OPENCC_S2T
    if OpenCC is None:
        raise RuntimeError("opencc-python-reimplemented is required to build ko_name")
    try:
        if _OPENCC_S2T is None:
            _OPENCC_S2T = OpenCC("s2t")
        return _OPENCC_S2T.convert(text)
    except Exception as exc:
        logger.debug("[StockDB] OpenCC conversion failed: %s", exc)
        return text


def _to_korean_hanja_reading(cn_name: str) -> str:
    cn_name = _clean_stock_name(cn_name)
    if not cn_name:
        return ""
    if hanja is None:
        raise RuntimeError("hanja is required to build ko_name")
    try:
        converted = hanja.translate(_to_traditional_chinese(cn_name), "substitution")
    except Exception as exc:
        logger.debug("[StockDB] Hanja conversion failed: %s", exc)
        return cn_name
    return _clean_stock_name(converted) or cn_name


def _stock_entry(
    cn_name: str,
    market: str,
    *,
    ticker: str = "",
    exchange: str = "",
    source: str = "akshare",
) -> dict[str, str]:
    cn_name = _clean_stock_name(cn_name)
    ko_name = _to_korean_hanja_reading(cn_name)
    return {
        "display_name": ko_name or cn_name,
        "cn_name": cn_name,
        "ko_name": ko_name,
        "market": market,
        "ticker": ticker or cn_name,
        "yahoo_ticker": ticker or cn_name,
        "exchange": exchange or market,
        "asset_type": "EQUITY",
        "status": "ACTIVE",
        "source": source,
        "schema_version": 2,
        "figi": "",
        "compositeFIGI": "",
        "shareClassFIGI": "",
        "isin": "",
    }
