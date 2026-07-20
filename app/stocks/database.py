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
    _stock_entry,
)
from stocks.universe import fetch_kr_listed, fetch_us_listed

logger = logging.getLogger(__name__)


class StockDatabase:
    def __init__(self, cache_file: Path, enabled: bool = True):
        self._cache_file = cache_file
        self._enabled = enabled
        self._db: dict[str, dict] = {}
        self._aliases: dict[str, str] | None = None  # 접미 코드 → universe 키

    def build(self) -> None:
        """종목 코드·이름 목록만 갱신한다. 시총·업종 보강은 enrich()를 별도로 실행."""
        db: dict[str, dict] = {}
        old_db = self._load_existing_cache()
        a_loaded = False
        hk_loaded = False
        try:
            df_a = _fetch_a_code_name()
            cols = list(df_a.columns)
            if "code" in cols:
                code_col, name_col = "code", "name"
            else:
                code_col, name_col = "股票代码", "股票名称"
            for _, row in df_a.iterrows():
                code = str(row[code_col]).zfill(6)
                cn_name = row[name_col]
                market = _classify_market(code)
                ticker = f"{code}.SS" if market == "SH" else f"{code}.SZ"
                entry = _stock_entry(cn_name, market, ticker=ticker, exchange=market)
                # 기존 시장 보강 데이터 보존
                old = old_db.get(code, {})
                for field in ("market_cap_cny", "industry"):
                    if old.get(field):
                        entry[field] = old[field]
                db[code] = entry
            a_loaded = True
            logger.info("[StockDB] A주 %d종목 로드", len(db))
        except Exception as e:
            logger.warning("[StockDB] A주 빌드 실패: %s", e)
            self._preserve_markets(db, old_db, {"SH", "SZ", "STAR", "CHI"})

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
                cn_name = row[hk_name_col]
                entry = _stock_entry(cn_name, "HK", ticker=f"{code.zfill(4)}.HK", exchange="HKEX")
                old = old_db.get(code, {})
                for field in ("market_cap_cny", "industry"):
                    if old.get(field):
                        entry[field] = old[field]
                db[code] = entry
            hk_loaded = True
            logger.info("[StockDB] 홍콩 %d종목 로드", len(db) - hk_before)
        except Exception as e:
            logger.warning("[StockDB] 홍콩 빌드 실패: %s", e)
            self._preserve_markets(db, old_db, {"HK"})

        self._build_market_universe(db, old_db, "KR", fetch_kr_listed)
        self._build_market_universe(db, old_db, "US", fetch_us_listed)

        if not a_loaded and not hk_loaded and not db:
            raise RuntimeError("A주와 홍콩 주식 DB 빌드가 모두 실패했습니다")

        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_file.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
        self._db = db
        self._aliases = None
        logger.info("[StockDB] DB 빌드 완료: 총 %d종목", len(db))

    @staticmethod
    def _build_market_universe(db: dict[str, dict], old_db: dict[str, dict], market: str, fetcher) -> None:
        try:
            rows = fetcher()
        except Exception as exc:
            logger.warning("[StockDB] %s universe collection failed: %s", market, exc)
            StockDatabase._preserve_markets(db, old_db, {market})
            return
        for row in rows:
            entry = {
                "display_name": str(row["display_name"]),
                "cn_name": "",
                "ko_name": str(row["display_name"]),
                "market": market,
                "ticker": str(row["code"]),
                "yahoo_ticker": str(row["yahoo_ticker"]),
                "exchange": str(row["exchange"]),
                "asset_type": str(row.get("asset_type") or "EQUITY"),
                "currency": str(row.get("currency") or ("KRW" if market == "KR" else "USD")),
                "status": "ACTIVE",
                "source": f"{market.lower()}-listed-universe",
                "schema_version": 3,
                "figi": "",
                "compositeFIGI": "",
                "shareClassFIGI": "",
                "isin": "",
            }
            db[str(row["key"])] = entry
        logger.info("[StockDB] %s universe loaded: %d tickers", market, len(rows))

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
        self._aliases = None
        logger.info("[StockDB] 캐시 로드: %d종목", len(self._db))

    def load_or_build(self) -> None:
        if not self._enabled:
            logger.info("[StockDB] STOCK_DB_ENABLED=false, 관련종목 기능 비활성화")
            return
        if self._cache_file.exists():
            try:
                self.load()
                if any(entry.get("schema_version") == 3 for entry in self._db.values()):
                    return
                logger.info("[StockDB] legacy schema detected; rebuilding universe")
            except Exception as e:
                logger.warning("[StockDB] 캐시 로드 실패, 재빌드: %s", e)
        try:
            self.build()
        except Exception as e:
            logger.warning("[StockDB] 빌드 실패, 빈 DB로 동작: %s", e)

    def _alias_index(self) -> dict[str, str]:
        """US:NASDAQ:AAPL 같은 universe 키를 접미 코드(AAPL)로 찾기 위한 색인."""
        if self._aliases is None:
            aliases: dict[str, str] = {}
            for key in self._db:
                if ":" in key:
                    aliases.setdefault(key.rsplit(":", 1)[-1], key)
            self._aliases = aliases
        return self._aliases

    def resolve_code(self, code: str) -> str | None:
        """DB 키 또는 별칭(티커·6자리 코드)을 정식 키로 해석. 없으면 None."""
        raw = str(code or "").strip()
        if not raw:
            return None
        if raw in self._db:
            return raw
        upper = raw.upper()
        if upper in self._db:
            return upper
        return self._alias_index().get(upper)

    def get_cn_name(self, code: str) -> str | None:
        entry = self._db.get(code)
        return entry["cn_name"] if entry else None

    def get_display_name(self, code: str) -> str | None:
        entry = self._db.get(code)
        return entry["display_name"] if entry else None

    def get_market(self, code: str) -> str | None:
        """코드가 실제 속한 시장(권위 있는 값)을 DB에서 조회. 뉴스 로그의 출처 기반
        market 태그(기사 단위)와 달리 종목별로 정확하다."""
        resolved = self.resolve_code(code)
        entry = self._db.get(resolved) if resolved else None
        return str(entry["market"]) if entry and entry.get("market") else None

    def is_valid_code(self, code: str) -> bool:
        return code in self._db

    def get_all(self) -> dict[str, dict]:
        return self._db.copy()

    def get_candidate_universe(self, limit: int | None = None) -> list[dict]:
        """리서치 후보 탐색용 종목 목록(코드·이름·시장·시총)."""
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
