"""StockDatabase: 종목 코드/이름 캐시의 빌드·보강·조회.

외부 데이터 수집·파싱·분류 유틸리티는 stock_db_sources 에 분리되어 있다.
"""

import json
import logging
from pathlib import Path
from typing import Callable

from stocks.sources import (
    _classify_market,
    _fetch_a_code_name,
    _fetch_hk_spot,
    _fetch_northbound_individual_a_codes,
    _is_foreign_individual_a_share_fallback,
    _is_foreign_individual_hk_security,
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
