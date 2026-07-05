"""리서치 후보군 확장: 강세 섹터 구성종목 + 问财 자연어 스크리닝(옵션).

모든 함수는 블로킹이므로 핸들러에서 asyncio.to_thread로 호출한다.
결과는 candidate_universe 항목과 같은 형태의 dict 목록이며, 실패는
빈 목록으로 조용히 처리한다(보조 소스).
"""

import logging
from typing import Any

from core.config import (
    RESEARCH_SECTOR_CANDIDATE_LIMIT,
    RESEARCH_SECTOR_CANDIDATES_ENABLED,
    WENCAI_CANDIDATE_LIMIT,
    WENCAI_ENABLED,
)
from research.candidates import _extract_research_cn_patterns
from stocks import StockDatabase

logger = logging.getLogger(__name__)

_SECTOR_BOARDS_TO_SCAN = 3


def _candidate_entry(
    code: str,
    name: str,
    market: str,
    watchlist: dict[str, str],
    relation_keyword: str,
    relation_reason: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "market": market,
        "in_watchlist": code in watchlist,
        "matched_news": [],
        "relation_keyword": relation_keyword,
        "relation_reason": relation_reason,
    }


def build_sector_candidates(
    quote_service,
    stock_db: StockDatabase,
    watchlist: dict[str, str],
    limit: int = RESEARCH_SECTOR_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    """오늘 강세 업종 보드의 구성종목 중 종목 DB(북향 가능) 적격 종목."""
    if not RESEARCH_SECTOR_CANDIDATES_ENABLED or quote_service is None:
        return []
    try:
        top_boards = quote_service.get_sector_rankings().get("top", [])
    except Exception as e:
        logger.warning("[DISCOVERY] 섹터 랭킹 조회 실패: %s", e)
        return []

    candidates: list[dict[str, Any]] = []
    for board in top_boards[:_SECTOR_BOARDS_TO_SCAN]:
        board_name = str(board.get("name") or "")
        if not board_name:
            continue
        pct = board.get("pct_change")
        pct_part = f" ({pct:+.2f}%)" if isinstance(pct, (int, float)) else ""
        for constituent in quote_service.get_sector_constituents(board_name):
            code = constituent["code"]
            if code in watchlist:
                continue
            display_name = stock_db.get_display_name(code)
            if not display_name:
                continue  # 북향 가능 목록 밖 → 제외
            candidates.append(
                _candidate_entry(
                    code,
                    display_name,
                    "",
                    watchlist,
                    relation_keyword=board_name,
                    relation_reason=f"오늘 강세 업종 {board_name}{pct_part} 구성종목",
                )
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def build_wencai_candidates(
    market_view: str,
    stock_db: StockDatabase,
    watchlist: dict[str, str],
    limit: int = WENCAI_CANDIDATE_LIMIT,
    query_override: str = "",
) -> list[dict[str, Any]]:
    """동화순 问财 자연어 스크리닝(비공식 API, 기본 비활성).

    pywencai가 설치되어 있지 않거나 호출이 실패하면 빈 목록을 반환한다.
    """
    if not WENCAI_ENABLED:
        return []
    try:
        import pywencai
    except ImportError:
        logger.warning("[DISCOVERY] WENCAI_ENABLED=true지만 pywencai가 없습니다. pip install pywencai")
        return []

    query = query_override.strip()
    if not query:
        patterns = _extract_research_cn_patterns(market_view)
        if not patterns:
            logger.info("[DISCOVERY] wencai 쿼리를 만들 중국어 키워드가 없어 건너뜁니다.")
            return []
        query = f"{' '.join(patterns[:3])} 相关上市公司"

    try:
        df = pywencai.get(query=query, loop=False)
    except Exception as e:
        logger.warning("[DISCOVERY] wencai 조회 실패: %s", e)
        return []
    if df is None or getattr(df, "empty", True):
        return []

    code_col = next((c for c in df.columns if "代码" in str(c)), None)
    name_col = next((c for c in df.columns if "简称" in str(c) or "名称" in str(c)), None)
    if code_col is None:
        return []

    candidates: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        raw = str(row[code_col])
        code = raw.split(".")[0].strip().zfill(6)
        if not code.isdigit() or code in watchlist:
            continue
        display_name = stock_db.get_display_name(code)
        if not display_name:
            continue
        candidates.append(
            _candidate_entry(
                code,
                display_name or (str(row[name_col]) if name_col else code),
                "",
                watchlist,
                relation_keyword="问财",
                relation_reason=f"问财 스크리닝 '{query}' 결과",
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def collect_extra_candidates(
    quote_service,
    stock_db: StockDatabase,
    watchlist: dict[str, str],
    market_view: str,
) -> list[dict[str, Any]]:
    """섹터·wencai 후보를 모아 코드 중복 없이 반환한다(블로킹)."""
    extras: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in (
        build_sector_candidates(quote_service, stock_db, watchlist)
        + build_wencai_candidates(market_view, stock_db, watchlist)
    ):
        code = candidate["code"]
        if code in seen:
            continue
        extras.append(candidate)
        seen.add(code)
    if extras:
        logger.info("[DISCOVERY] 추가 후보 %d개 (섹터/问财)", len(extras))
    return extras
