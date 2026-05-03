import json
import logging
from pathlib import Path

import akshare as ak
import requests.exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


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

        try:
            df_a = _fetch_a_code_name()
            if "code" in df_a.columns:
                code_col, name_col = "code", "name"
            else:
                code_col, name_col = "股票代码", "股票名称"
            for _, row in df_a.iterrows():
                code = str(row[code_col]).zfill(6)
                db[code] = {"name": str(row[name_col]), "market": _classify_market(code)}
            a_loaded = True
            logger.info("[StockDB] A주 %d종목 로드", len(db))
        except Exception as e:
            logger.warning("[StockDB] A주 빌드 실패: %s", e)
            self._preserve_markets(db, old_db, {"SH", "SZ", "STAR", "CHI"})

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
                db[code] = {"name": str(row[hk_name_col]), "market": "HK"}
            hk_loaded = True
            logger.info("[StockDB] 홍콩 %d종목 로드", len(db) - hk_before)
        except Exception as e:
            logger.warning("[StockDB] 홍콩 빌드 실패: %s", e)
            self._preserve_markets(db, old_db, {"HK"})

        if not a_loaded and not hk_loaded:
            if old_db:
                self._db = old_db
                logger.warning("[StockDB] 전체 빌드 실패, 기존 캐시 유지: %d종목", len(old_db))
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
    def _preserve_markets(
        db: dict[str, dict],
        old_db: dict[str, dict],
        markets: set[str],
    ) -> None:
        for code, entry in old_db.items():
            if entry.get("market") in markets and code not in db:
                db[code] = entry

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
        return entry["name"] if entry else None

    def is_valid_code(self, code: str) -> bool:
        return code in self._db

    def get_all(self) -> dict[str, dict]:
        return self._db.copy()

    def get_candidate_universe(self, limit: int | None = None) -> list[dict[str, str]]:
        items = [
            {
                "code": code,
                "name": str(entry.get("name") or ""),
                "market": str(entry.get("market") or ""),
            }
            for code, entry in self._db.items()
        ]
        return items[:limit] if limit else items
