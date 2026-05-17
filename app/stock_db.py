import csv
import io
import json
import logging
import re
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
_CACHE_SCHEMA_VERSION = 5
_HKEX_NORTHBOUND_BUY_SELL_XLS_URLS = (
    "https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/"
    "Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities_xls/SSE_Securities.xls",
    "https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/"
    "Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities_xls/SZSE_Securities.xls",
)
_INDIVIDUAL_RESTRICTED_A_PREFIXES = ("300", "301", "688", "689")


def _retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (requests.exceptions.RequestException, ConnectionError, TimeoutError)
        ),
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
    # HKD ordinary equity counters are kept. 8xxxx RMB counters are duplicate
    # counters that many retail brokers do not expose as regular HK equities.
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
        "eligibility": "foreign_individual",
        "schema_version": str(_CACHE_SCHEMA_VERSION),
    }


class StockDatabase:
    def __init__(self, cache_file: Path, enabled: bool = True):
        self._cache_file = cache_file
        self._enabled = enabled
        self._db: dict[str, dict] = {}

    def build(self) -> None:
        db: dict[str, dict] = {}
        old_db = self._load_existing_cache()
        a_loaded = False
        hk_loaded = False
        northbound_codes: set[str] | None = None

        try:
            northbound_codes = _fetch_northbound_individual_a_codes()
            if not northbound_codes:
                raise RuntimeError("HKEX Northbound eligible code list is empty")
            logger.info("[StockDB] HKEX 개인투자자 가능 A주 %d종목 로드", len(northbound_codes))
        except Exception as e:
            logger.warning("[StockDB] HKEX 가능 A주 목록 로드 실패, 코드 규칙 fallback 사용: %s", e)

        try:
            df_a = _fetch_a_code_name()
            cols = list(df_a.columns)
            if "code" in cols:
                code_col, name_col = "code", "name"
            else:
                code_col, name_col = "股票代码", "股票名称"
            for _, row in df_a.iterrows():
                code = str(row[code_col]).zfill(6)
                if northbound_codes is not None:
                    if code not in northbound_codes:
                        continue
                elif not _is_foreign_individual_a_share_fallback(code):
                    continue
                cn_name = row[name_col]
                db[code] = _stock_entry(cn_name, _classify_market(code))
            a_loaded = True
            logger.info("[StockDB] A주 %d종목 로드", len(db))
        except Exception as e:
            logger.warning("[StockDB] A주 빌드 실패: %s", e)
            if northbound_codes is not None:
                self._preserve_markets(
                    db,
                    old_db,
                    {"SH", "SZ", "STAR", "CHI"},
                    code_filter=lambda code: code in northbound_codes,
                )
            else:
                self._preserve_markets(
                    db,
                    old_db,
                    {"SH", "SZ", "STAR", "CHI"},
                    code_filter=_is_foreign_individual_a_share_fallback,
                )

        hk_before = len(db)
        try:
            df_hk = _fetch_hk_spot()
            # stock_hk_spot(): 代码(col1), 中文名称(col2)
            # stock_hk_spot_em(): 代码(col0), 名称(col1) — 혹시 fallback 시 대응
            cols = list(df_hk.columns)
            if "代码" in cols and "中文名称" in cols:
                hk_code_col, hk_name_col = "代码", "中文名称"
            elif "代码" in cols and "名称" in cols:
                hk_code_col, hk_name_col = "代码", "名称"
            else:
                hk_code_col, hk_name_col = cols[1], cols[2]
            for _, row in df_hk.iterrows():
                code = str(row[hk_code_col]).zfill(5)
                if not _is_foreign_individual_hk_security(code):
                    continue
                cn_name = row[hk_name_col]
                db[code] = _stock_entry(cn_name, "HK")
            hk_loaded = True
            logger.info("[StockDB] 홍콩 %d종목 로드", len(db) - hk_before)
        except Exception as e:
            logger.warning("[StockDB] 홍콩 빌드 실패: %s", e)
            self._preserve_markets(
                db,
                old_db,
                {"HK"},
                code_filter=_is_foreign_individual_hk_security,
            )

        if not a_loaded and not hk_loaded and not db:
            if old_db:
                self._db = self._filter_existing_cache(old_db)
                logger.warning("[StockDB] 전체 빌드 실패, 필터된 기존 캐시 유지: %d종목", len(self._db))
                return
            raise RuntimeError("A주와 홍콩 주식 DB 빌드가 모두 실패했습니다")

        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_file.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
        self._db = db
        logger.info("[StockDB] DB 빌드 완료: 총 %d종목", len(db))

    def _load_existing_cache(self) -> dict[str, dict]:
        if not self._cache_file.exists():
            return {}
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[StockDB] 기존 캐시 읽기 실패: %s", e)
            return {}

    @staticmethod
    def _has_name_metadata(db: dict[str, dict]) -> bool:
        if not db:
            return True
        return all(
            isinstance(entry, dict)
            and "display_name" in entry
            and "cn_name" in entry
            and "ko_name" in entry
            and bool(entry.get("ko_name"))
            and entry.get("display_name") == entry.get("ko_name")
            and entry.get("eligibility") == "foreign_individual"
            and entry.get("schema_version") == str(_CACHE_SCHEMA_VERSION)
            for entry in db.values()
        )

    @staticmethod
    def _preserve_markets(
        db: dict[str, dict],
        old_db: dict[str, dict],
        markets: set[str],
        code_filter: Callable[[str], bool] | None = None,
    ) -> None:
        for code, entry in old_db.items():
            if entry.get("market") not in markets or code in db:
                continue
            if code_filter is not None and not code_filter(code):
                continue
            cn_name = str(
                entry.get("cn_name")
                or entry.get("display_name")
                or entry.get("name")
                or ""
            )
            db[code] = _stock_entry(cn_name, str(entry.get("market") or ""))

    @classmethod
    def _filter_existing_cache(cls, old_db: dict[str, dict]) -> dict[str, dict]:
        db: dict[str, dict] = {}
        cls._preserve_markets(
            db,
            old_db,
            {"SH", "SZ", "STAR", "CHI"},
            code_filter=_is_foreign_individual_a_share_fallback,
        )
        cls._preserve_markets(
            db,
            old_db,
            {"HK"},
            code_filter=_is_foreign_individual_hk_security,
        )
        return db

    def load(self) -> None:
        self._db = json.loads(self._cache_file.read_text(encoding="utf-8"))
        logger.info("[StockDB] 캐시 로드: %d종목", len(self._db))

    def load_or_build(self) -> None:
        if not self._enabled:
            logger.info("[StockDB] STOCK_DB_ENABLED=false, 관련종목 기능 비활성화")
            return
        if self._cache_file.exists():
            try:
                self.load()
                if self._has_name_metadata(self._db):
                    return
                logger.info("[StockDB] 구버전 캐시 감지, 한국 한자음 표시 DB로 재빌드")
            except Exception as e:
                logger.warning("[StockDB] 캐시 로드 실패, 재빌드: %s", e)
        try:
            self.build()
        except Exception as e:
            logger.warning("[StockDB] 빌드 실패, 빈 DB로 동작: %s", e)

    def get_cn_name(self, code: str) -> str | None:
        entry = self._db.get(code)
        return entry["cn_name"] if entry else None

    def get_display_name(self, code: str) -> str | None:
        entry = self._db.get(code)
        return entry["display_name"] if entry else None

    def is_valid_code(self, code: str) -> bool:
        return code in self._db

    def get_all(self) -> dict[str, dict]:
        return self._db.copy()

    def get_candidate_universe(self, limit: int | None = None) -> list[dict[str, str]]:
        items = [
            {
                "code": code,
                "display_name": str(entry.get("display_name") or ""),
                "cn_name": str(entry.get("cn_name") or entry.get("display_name") or ""),
                "ko_name": str(entry.get("ko_name") or ""),
                "market": str(entry.get("market") or ""),
            }
            for code, entry in self._db.items()
        ]
        return items[:limit] if limit else items
