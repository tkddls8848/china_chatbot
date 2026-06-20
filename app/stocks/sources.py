import csv
import io
import json
import logging
import os
import re
import time
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import pandas as pd
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
_HKEX_NORTHBOUND_BUY_SELL_XLS_URLS = (
    "https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/"
    "Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities_xls/SSE_Securities.xls",
    "https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/"
    "Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities_xls/SZSE_Securities.xls",
)
_INDIVIDUAL_RESTRICTED_A_PREFIXES = ("300", "301", "688", "689")
NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
    RemoteDisconnected,
)


def _retry_on_network(func):
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


@_retry_on_network
def _fetch_hkex_file(url: str) -> bytes:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.content


# ── EODHD 관련 함수 ───────────────────────────────────────────────────────────

_EODHD_BASE = "https://eodhd.com/api"

_MARKET_TO_EODHD_EXCHANGE: dict[str, str] = {
    "SH": "SHG",
    "STAR": "SHG",
    "SZ": "SHE",
    "CHI": "SHE",
    "HK": "HK",
}


def _eodhd_exchange(market: str) -> str:
    return _MARKET_TO_EODHD_EXCHANGE.get(market, "")


def _eodhd_code(code: str, market: str) -> str:
    """앱 내부 코드 → EODHD 심볼 코드 (거래소 접미사 제외)."""
    if market == "HK":
        return f"{int(code):04d}"
    return code


@_retry_on_network
def _fetch_eodhd_fundamentals(symbol: str, exchange: str, token: str) -> dict:
    resp = requests.get(
        f"{_EODHD_BASE}/fundamentals/{symbol}.{exchange}",
        params={"api_token": token, "fmt": "json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_eodhd_entry(item: dict) -> tuple[str, str, float, str]:
    """(sector, industry, market_cap, currency) 추출. market_cap은 로컬 통화 기준."""
    general = item.get("General") or item
    sector = str(general.get("Sector") or "").strip()
    industry = str(general.get("Industry") or "").strip()
    currency = str(general.get("CurrencyCode") or general.get("Currency") or "").upper()

    market_cap = 0.0
    for src in (general, item.get("Highlights") or {}, item):
        for key in ("MarketCapitalization", "marketCapitalization", "market_cap"):
            raw = src.get(key)
            if raw:
                try:
                    v = float(raw)
                    if v > 0:
                        market_cap = v
                        break
                except (TypeError, ValueError):
                    pass
        if market_cap > 0:
            break

    return sector, industry, market_cap, currency


def _fetch_hkd_cny_rate() -> float:
    try:
        df = ak.currency_latest(symbol="HKDCNY")
        rate = float(df.iloc[0, -1])
        if 0.5 < rate < 2.0:
            return rate
    except Exception as e:
        logger.debug("[StockDB] HKD/CNY 환율 조회 실패, 0.92 사용: %s", e)
    return 0.92


# ── 기존 유틸리티 함수 ────────────────────────────────────────────────────

def _classify_market(code: str) -> str:
    if len(code) <= 5:
        return "HK"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("300", "301")):
        return "CHI"
    if code.startswith("6"):
        return "SH"
    return "SZ"


def _is_professional_only_a_share(code: str) -> bool:
    return code.startswith(_INDIVIDUAL_RESTRICTED_A_PREFIXES)


def _is_foreign_individual_a_share_fallback(code: str) -> bool:
    if not re.fullmatch(r"\d{6}", code):
        return False
    if _is_professional_only_a_share(code):
        return False
    return code.startswith(("0", "6"))


def _is_foreign_individual_hk_security(code: str) -> bool:
    if not re.fullmatch(r"\d{5}", code):
        return False
    return not code.startswith("8")


def _normalize_a_share_code_candidate(value: Any) -> str | None:
    text = str(value).strip()
    if re.fullmatch(r"\d{1,6}", text):
        code = text.zfill(6)
        return code if code.startswith(("0", "3", "6")) else None
    return None


def _extract_a_share_codes_from_csv(text: str) -> set[str]:
    codes: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            for match in re.findall(r"(?<!\d)[036]\d{5}(?!\d)", str(cell)):
                codes.add(match)
            if code := _normalize_a_share_code_candidate(cell):
                codes.add(code)
    return codes


def _extract_a_share_codes_from_excel(content: bytes) -> set[str]:
    df = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    codes: set[str] = set()
    for value in df.to_numpy().ravel():
        if pd.isna(value):
            continue
        for match in re.findall(r"(?<!\d)[036]\d{5}(?!\d)", str(value)):
            codes.add(match)
        if code := _normalize_a_share_code_candidate(value):
            codes.add(code)
    return codes


def _extract_a_share_codes_from_hkex_file(content: bytes) -> set[str]:
    try:
        return _extract_a_share_codes_from_excel(content)
    except Exception:
        text = content.decode("utf-8-sig", errors="ignore")
        return _extract_a_share_codes_from_csv(text)


def _fetch_northbound_individual_a_codes() -> set[str]:
    codes: set[str] = set()
    for url in _HKEX_NORTHBOUND_BUY_SELL_XLS_URLS:
        codes.update(_extract_a_share_codes_from_hkex_file(_fetch_hkex_file(url)))
    return {
        code
        for code in codes
        if not _is_professional_only_a_share(code)
    }


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
    except Exception as e:
        logger.debug("[StockDB] OpenCC conversion failed: %s", e)
        return text


def _to_korean_hanja_reading(cn_name: str) -> str:
    cn_name = _clean_stock_name(cn_name)
    if not cn_name:
        return ""
    if hanja is None:
        raise RuntimeError("hanja is required to build ko_name")
    text = _to_traditional_chinese(cn_name)
    try:
        converted = hanja.translate(text, "substitution")
    except Exception as e:
        logger.debug("[StockDB] Hanja conversion failed: %s", e)
        return cn_name

    converted = _clean_stock_name(converted)
    return converted or cn_name


def _stock_entry(cn_name: str, market: str) -> dict[str, str]:
    cn_name = _clean_stock_name(cn_name)
    ko_name = _to_korean_hanja_reading(cn_name)
    return {
        "display_name": ko_name or cn_name,
        "cn_name": cn_name,
        "ko_name": ko_name,
        "market": market,
    }


