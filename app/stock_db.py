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


def _classify_industries_via_llm(
    items: list[str],
    sector_defs: dict,
    base_url: str,
    model: str,
    timeout: int = 120,
) -> dict[str, str]:
    if not items or not sector_defs:
        return {}
    system_prompt = (
        "你是股票行业分类专家。根据提供的主题板块定义，将items列表中每个行业名称"
        "映射到最合适的sector_id（如semiconductor、battery_ev等）。"
        "如果不属于任何板块，映射为\"etc\"。"
        "仅返回JSON对象，格式：{\"行业名\": \"sector_id\", ...}"
    )
    payload = {"items": items, "sectors": sector_defs}
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    {"role": "assistant", "content": "{"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = (resp.json().get("message") or {}).get("content", "")
        if not content.lstrip().startswith("{"):
            content = "{" + content
        result = json.loads(content)
        if isinstance(result, dict):
            return {str(k): str(v) for k, v in result.items()}
    except Exception as e:
        logger.warning("[StockDB] LLM 섹터 분류 실패: %s", e)
    return {}


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


class StockDatabase:
    def __init__(self, cache_file: Path, enabled: bool = True):
        self._cache_file = cache_file
        self._enabled = enabled
        self._db: dict[str, dict] = {}

    def build(self) -> None:
        """종목 코드·이름 목록만 갱신한다. 시총·업종 보강은 enrich()를 별도로 실행."""
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
                entry = _stock_entry(cn_name, _classify_market(code))
                # 기존 enrichment 데이터 보존
                old = old_db.get(code, {})
                for field in ("market_cap_cny", "sector", "industry", "schema_version"):
                    if old.get(field):
                        entry[field] = old[field]
                db[code] = entry
            a_loaded = True
            logger.info("[StockDB] A주 %d종목 로드", len(db))
        except Exception as e:
            logger.warning("[StockDB] A주 빌드 실패: %s", e)
            if northbound_codes is not None:
                self._preserve_markets(
                    db, old_db, {"SH", "SZ", "STAR", "CHI"},
                    code_filter=lambda code: code in northbound_codes,
                )
            else:
                self._preserve_markets(
                    db, old_db, {"SH", "SZ", "STAR", "CHI"},
                    code_filter=_is_foreign_individual_a_share_fallback,
                )

        hk_before = len(db)
        try:
            df_hk = _fetch_hk_spot()
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
                entry = _stock_entry(cn_name, "HK")
                old = old_db.get(code, {})
                for field in ("market_cap_cny", "sector", "industry", "schema_version"):
                    if old.get(field):
                        entry[field] = old[field]
                db[code] = entry
            hk_loaded = True
            logger.info("[StockDB] 홍콩 %d종목 로드", len(db) - hk_before)
        except Exception as e:
            logger.warning("[StockDB] 홍콩 빌드 실패: %s", e)
            self._preserve_markets(
                db, old_db, {"HK"},
                code_filter=_is_foreign_individual_hk_security,
            )

        if not a_loaded and not hk_loaded and not db:
            raise RuntimeError("A주와 홍콩 주식 DB 빌드가 모두 실패했습니다")

        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_file.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
        self._db = db
        logger.info("[StockDB] DB 빌드 완료: 총 %d종목", len(db))

    def enrich(self) -> None:
        """EODHD API로 시가총액·업종·섹터를 보강하고 캐시에 저장한다.
        EODHD_API_TOKEN 환경변수 필요. 봇 시작 시 자동 실행하지 않는다.
        """
        if not self._db:
            logger.warning("[StockDB] DB가 비어있음, enrich 전에 load 또는 build 필요")
            return

        token = os.environ.get("EODHD_API_TOKEN", "").strip()
        if not token:
            logger.warning("[StockDB] EODHD_API_TOKEN 미설정, enrich 생략")
            return

        ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.environ.get(
            "RESEARCH_ANALYSIS_MODEL",
            os.environ.get("TRANSLATION_MODEL", "gemma4"),
        )

        sector_defs_path = self._cache_file.parent / "momentum" / "industry_keywords.json"
        try:
            sector_defs: dict = json.loads(sector_defs_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[StockDB] 섹터 정의 로드 실패: %s", e)
            sector_defs = {}

        # 미보강 종목만 선별 (sector 또는 market_cap_cny 없는 것)
        limit = int(os.environ.get("EODHD_ENRICH_LIMIT", "200"))
        call_delay = float(os.environ.get("EODHD_ENRICH_DELAY", "0.5"))

        targets = [
            (code, entry)
            for code, entry in self._db.items()
            if not entry.get("sector") or not float(entry.get("market_cap_cny") or 0) > 0
        ][:limit]

        hkd_cny = _fetch_hkd_cny_rate()
        total_unenriched = sum(
            1 for e in self._db.values()
            if not e.get("sector") or not float(e.get("market_cap_cny") or 0) > 0
        )
        print(f"[StockDB] EODHD 보강 시작: {len(targets)}종목 조회 (전체 미보강 {total_unenriched}종목)")

        # 개별 fundamentals 호출
        fetch_results: dict[str, dict] = {}
        failures = 0
        for i, (code, entry) in enumerate(targets):
            market = entry.get("market", "")
            exchange = _eodhd_exchange(market)
            if not exchange:
                print(f"  [{i+1:>3}/{len(targets)}] {code} SKIP (exchange 없음)")
                continue
            symbol = _eodhd_code(code, market)
            try:
                data = _fetch_eodhd_fundamentals(symbol, exchange, token)
                sector, industry, market_cap, currency = _parse_eodhd_entry(data)
                fetch_results[code] = {
                    "sector": sector, "industry": industry,
                    "market_cap": market_cap, "currency": currency,
                }
                failures = 0
                cap_str = f"{market_cap/1e8:.0f}억" if market_cap > 0 else "시총없음"
                print(f"  [{i+1:>3}/{len(targets)}] {symbol}.{exchange} OK  {sector or '섹터없음'} / {industry or '업종없음'} / {cap_str}")
            except Exception as e:
                failures += 1
                print(f"  [{i+1:>3}/{len(targets)}] {symbol}.{exchange} FAIL({failures}) {type(e).__name__}: {e}")
                if failures >= 5:
                    print(f"  연속 5회 실패, 조회 중단")
                    break
            if i < len(targets) - 1:
                time.sleep(call_delay)

        print(f"[StockDB] EODHD 조회 완료: {len(fetch_results)}/{len(targets)}종목 성공")

        # Sector 공란인 Industry → LLM 폴백
        industries_needing_llm: set[str] = {
            info["industry"]
            for info in fetch_results.values()
            if not info.get("sector") and info.get("industry")
        }
        industry_sector_fallback: dict[str, str] = {}
        if sector_defs and industries_needing_llm:
            print(f"[StockDB] LLM 폴백 분류 시작: Sector 공란 {len(industries_needing_llm)}개 업종")
            industry_sector_fallback = _classify_industries_via_llm(
                list(industries_needing_llm), sector_defs, ollama_base_url, ollama_model, timeout=180
            )
            print(f"[StockDB] LLM 폴백 분류 완료: {len(industry_sector_fallback)}개")

        # DB 주입
        enriched = 0
        for code, info in fetch_results.items():
            entry = self._db.get(code)
            if entry is None:
                continue
            market = entry.get("market", "")
            sector = str(info.get("sector") or "").strip()
            industry = str(info.get("industry") or "")
            raw_cap = float(info.get("market_cap") or 0)
            currency = str(info.get("currency") or "").upper()

            if raw_cap > 0:
                market_cap_cny = raw_cap * hkd_cny if (market == "HK" and currency in ("", "HKD")) else raw_cap
                enriched += 1
            else:
                market_cap_cny = float(entry.get("market_cap_cny") or 0)

            entry["market_cap_cny"] = market_cap_cny
            entry["industry"] = industry
            entry["sector"] = sector or industry_sector_fallback.get(industry) or entry.get("sector") or ""
            entry["schema_version"] = "6"

        self._cache_file.write_text(json.dumps(self._db, ensure_ascii=False), encoding="utf-8")

        remaining = sum(
            1 for e in self._db.values()
            if not e.get("sector") or not float(e.get("market_cap_cny") or 0) > 0
        )
        print(f"[StockDB] 보강 완료: {enriched}종목 시총 갱신, 잔여 미보강 {remaining}종목")

    def _load_existing_cache(self) -> dict[str, dict]:
        if not self._cache_file.exists():
            return {}
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[StockDB] 기존 캐시 읽기 실패: %s", e)
            return {}

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
                return
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

    def get_candidate_universe(self, limit: int | None = None) -> list[dict]:
        items = [
            {
                "code": code,
                "display_name": str(entry.get("display_name") or ""),
                "cn_name": str(entry.get("cn_name") or entry.get("display_name") or ""),
                "ko_name": str(entry.get("ko_name") or ""),
                "market": str(entry.get("market") or ""),
                "market_cap_cny": float(entry.get("market_cap_cny") or 0.0),
                "sector": str(entry.get("sector") or ""),
            }
            for code, entry in self._db.items()
        ]
        return items[:limit] if limit else items
