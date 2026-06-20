"""StockDatabase: 종목 코드/이름 캐시의 빌드·보강·조회.

외부 데이터 수집·파싱·분류 유틸리티는 stock_db_sources 에 분리되어 있다.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

from stocks.sources import (
    _classify_market,
    _eodhd_code,
    _eodhd_exchange,
    _fetch_a_code_name,
    _fetch_eodhd_fundamentals,
    _fetch_hk_spot,
    _fetch_hkd_cny_rate,
    _fetch_northbound_individual_a_codes,
    _is_foreign_individual_a_share_fallback,
    _is_foreign_individual_hk_security,
    _parse_eodhd_entry,
    _stock_entry,
)

logger = logging.getLogger(__name__)


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
                for field in ("market_cap_cny", "industry", "schema_version"):
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
                for field in ("market_cap_cny", "industry", "schema_version"):
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

        # 미보강 종목만 선별 (market_cap_cny 없는 것)
        limit = int(os.environ.get("EODHD_ENRICH_LIMIT", "200"))
        call_delay = float(os.environ.get("EODHD_ENRICH_DELAY", "0.5"))

        targets = [
            (code, entry)
            for code, entry in self._db.items()
            if not float(entry.get("market_cap_cny") or 0) > 0
        ][:limit]

        hkd_cny = _fetch_hkd_cny_rate()
        total_unenriched = sum(
            1 for e in self._db.values()
            if not float(e.get("market_cap_cny") or 0) > 0
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
                _sector, industry, market_cap, currency = _parse_eodhd_entry(data)
                fetch_results[code] = {
                    "industry": industry,
                    "market_cap": market_cap, "currency": currency,
                }
                failures = 0
                cap_str = f"{market_cap/1e8:.0f}억" if market_cap > 0 else "시총없음"
                print(f"  [{i+1:>3}/{len(targets)}] {symbol}.{exchange} OK  {industry or '업종없음'} / {cap_str}")
            except Exception as e:
                failures += 1
                print(f"  [{i+1:>3}/{len(targets)}] {symbol}.{exchange} FAIL({failures}) {type(e).__name__}: {e}")
                if failures >= 5:
                    print(f"  연속 5회 실패, 조회 중단")
                    break
            if i < len(targets) - 1:
                time.sleep(call_delay)

        print(f"[StockDB] EODHD 조회 완료: {len(fetch_results)}/{len(targets)}종목 성공")

        # DB 주입
        enriched = 0
        for code, info in fetch_results.items():
            entry = self._db.get(code)
            if entry is None:
                continue
            market = entry.get("market", "")
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
            entry["schema_version"] = "6"

        self._cache_file.write_text(json.dumps(self._db, ensure_ascii=False), encoding="utf-8")

        remaining = sum(
            1 for e in self._db.values()
            if not float(e.get("market_cap_cny") or 0) > 0
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
            }
            for code, entry in self._db.items()
        ]
        return items[:limit] if limit else items
