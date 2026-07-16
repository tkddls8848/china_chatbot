"""정량 컨텍스트: 시세·자금흐름·섹터·인기순위·涨停·용호방 스냅샷.

AkShare 원시 지표를 요약해 (a) 브리핑 메시지와 (b) 시장뷰 분석 payload에
주입한다. 자체 스코어링·백테스트는 하지 않는다(원시 지표 요약까지만).
모든 조회는 블로킹이므로 asyncio.to_thread로 호출해야 하며, 시장 전체
테이블은 TTL 캐시로 재사용한다.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


class _TTLCache:
    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get_or_fetch(self, key: str, fetch: Callable[[], Any]):
        now = time.monotonic()
        cached = self._store.get(key)
        if cached and now - cached[0] < self._ttl:
            return cached[1]
        value = fetch()
        self._store[key] = (now, value)
        return value


class QuoteService:
    """관심종목·시장 정량 스냅샷 제공자(블로킹, to_thread에서 호출)."""

    def __init__(self, enabled: bool = True, cache_ttl_minutes: int = 10, sector_top_n: int = 5):
        self._enabled = enabled
        self._cache = _TTLCache(ttl_seconds=max(1, cache_ttl_minutes) * 60)
        self._sector_top_n = max(1, sector_top_n)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── 시세 ─────────────────────────────────────────

    def _a_spot(self) -> pd.DataFrame:
        return self._cache.get_or_fetch("a_spot", ak.stock_zh_a_spot_em)

    def _hk_spot(self) -> pd.DataFrame:
        return self._cache.get_or_fetch("hk_spot", ak.stock_hk_spot_em)

    def get_watchlist_quotes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        """코드별 {price, pct_change, amount}. 실패한 시장은 조용히 비운다."""
        if not self._enabled or not codes:
            return {}
        a_codes = [c for c in codes if len(c) == 6]
        hk_codes = [c for c in codes if len(c) == 5]
        quotes: dict[str, dict[str, Any]] = {}

        if a_codes:
            try:
                df = self._a_spot()
                rows = df[df["代码"].astype(str).isin(a_codes)]
                for _, row in rows.iterrows():
                    quotes[str(row["代码"])] = {
                        "price": _safe_float(row.get("最新价")),
                        "pct_change": _safe_float(row.get("涨跌幅")),
                        "amount": _safe_float(row.get("成交额")),
                    }
            except Exception as e:
                logger.warning("[QUANT] A주 시세 조회 실패: %s", e)

        if hk_codes:
            try:
                df = self._hk_spot()
                rows = df[df["代码"].astype(str).str.zfill(5).isin(hk_codes)]
                for _, row in rows.iterrows():
                    quotes[str(row["代码"]).zfill(5)] = {
                        "price": _safe_float(row.get("最新价")),
                        "pct_change": _safe_float(row.get("涨跌幅")),
                        "amount": _safe_float(row.get("成交额")),
                    }
            except Exception as e:
                logger.warning("[QUANT] HK 시세 조회 실패: %s", e)

        return quotes

    def get_price(self, code: str) -> float | None:
        """관심리스트 이벤트 기록용 현재가(최선 노력)."""
        try:
            return self.get_watchlist_quotes([code]).get(code, {}).get("price")
        except Exception:
            return None

    # ── 자금 흐름 ────────────────────────────────────

    def get_fund_flow(self, code: str) -> dict[str, Any] | None:
        """A주 개별 종목 최근 거래일 주력 자금 순유입. HK는 미지원(None)."""
        if not self._enabled or len(code) != 6:
            return None
        market = "sh" if code.startswith("6") else "sz"
        try:
            df = self._cache.get_or_fetch(
                f"fund_flow:{code}",
                lambda: ak.stock_individual_fund_flow(stock=code, market=market),
            )
            if df is None or df.empty:
                return None
            row = df.iloc[-1]
            return {
                "date": str(row.get("日期") or ""),
                "main_net_inflow": _safe_float(row.get("主力净流入-净额")),
                "main_net_inflow_pct": _safe_float(row.get("主力净流入-净占比")),
            }
        except Exception as e:
            logger.warning("[QUANT] %s 자금흐름 조회 실패: %s", code, e)
            return None

    # ── 섹터/시장 온도 ───────────────────────────────

    def get_sector_rankings(self) -> dict[str, list[dict[str, Any]]]:
        """동방재부 업종 보드 등락률 상·하위 N개."""
        if not self._enabled:
            return {"top": [], "bottom": []}
        try:
            df = self._cache.get_or_fetch("industry_boards", ak.stock_board_industry_name_em)
            df = df.copy()
            df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
            df = df.dropna(subset=["涨跌幅"]).sort_values("涨跌幅", ascending=False)

            def rows_to_list(rows) -> list[dict[str, Any]]:
                return [
                    {
                        "name": str(row["板块名称"]),
                        "pct_change": _safe_float(row["涨跌幅"]),
                        "leader": str(row.get("领涨股票") or ""),
                    }
                    for _, row in rows.iterrows()
                ]

            return {
                "top": rows_to_list(df.head(self._sector_top_n)),
                "bottom": rows_to_list(df.tail(self._sector_top_n).iloc[::-1]),
            }
        except Exception as e:
            logger.warning("[QUANT] 섹터 보드 조회 실패: %s", e)
            return {"top": [], "bottom": []}

    def get_sector_constituents(self, board_name: str) -> list[dict[str, str]]:
        """업종 보드 구성종목(리서치 후보군 발굴용)."""
        if not self._enabled:
            return []
        try:
            df = self._cache.get_or_fetch(
                f"board_cons:{board_name}",
                lambda: ak.stock_board_industry_cons_em(symbol=board_name),
            )
            return [
                {"code": str(row["代码"]).zfill(6), "name": str(row["名称"])}
                for _, row in df.iterrows()
            ]
        except Exception as e:
            logger.warning("[QUANT] %s 구성종목 조회 실패: %s", board_name, e)
            return []

    def get_hot_rank_hits(self, codes: list[str]) -> list[dict[str, Any]]:
        """동방재부 인기순위에 든 관심종목."""
        if not self._enabled or not codes:
            return []
        try:
            df = self._cache.get_or_fetch("hot_rank", ak.stock_hot_rank_em)
            hits = []
            for _, row in df.iterrows():
                raw = str(row.get("代码") or "")
                code = raw[2:] if raw[:2].upper() in ("SH", "SZ", "BJ") else raw
                if code in codes:
                    hits.append(
                        {
                            "code": code,
                            "name": str(row.get("股票名称") or ""),
                            "rank": int(_safe_float(row.get("当前排名")) or 0),
                        }
                    )
            return hits
        except Exception as e:
            logger.warning("[QUANT] 인기순위 조회 실패: %s", e)
            return []

    def get_zt_pool_summary(self) -> dict[str, Any]:
        """오늘 涨停 종목 수와 상위 몇 종목(단기 과열 온도계)."""
        if not self._enabled:
            return {}
        try:
            date = datetime.now().strftime("%Y%m%d")
            df = self._cache.get_or_fetch(
                f"zt_pool:{date}", lambda: ak.stock_zt_pool_em(date=date)
            )
            if df is None or df.empty:
                return {"count": 0, "names": []}
            return {
                "count": int(len(df)),
                "names": [str(n) for n in df["名称"].head(5).tolist()],
            }
        except Exception as e:
            logger.warning("[QUANT] 涨停 풀 조회 실패: %s", e)
            return {}

    def get_lhb_hits(self, codes: list[str], lookback_days: int = 5) -> list[dict[str, Any]]:
        """최근 용호방(龙虎榜)에 오른 관심종목."""
        if not self._enabled or not codes:
            return []
        try:
            end = datetime.now()
            start = end - timedelta(days=max(1, lookback_days))
            df = self._cache.get_or_fetch(
                f"lhb:{end.strftime('%Y%m%d')}",
                lambda: ak.stock_lhb_detail_em(
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                ),
            )
            if df is None or df.empty:
                return []
            hits = []
            for _, row in df.iterrows():
                code = str(row.get("代码") or "").zfill(6)
                if code in codes:
                    hits.append(
                        {
                            "code": code,
                            "name": str(row.get("名称") or ""),
                            "date": str(row.get("上榜日") or ""),
                            "reason": str(row.get("解读") or row.get("上榜原因") or ""),
                        }
                    )
            return hits
        except Exception as e:
            logger.warning("[QUANT] 용호방 조회 실패: %s", e)
            return []

    # ── 종합 스냅샷 ──────────────────────────────────

    def build_quant_context(
        self,
        watchlist: dict[str, str],
        include_fund_flow: bool = True,
    ) -> dict[str, Any]:
        """브리핑·시장뷰 분석에 주입할 정량 스냅샷. 각 항목은 최선 노력."""
        if not self._enabled:
            return {}
        codes = list(watchlist.keys())
        quotes = self.get_watchlist_quotes(codes)

        watchlist_rows = []
        for code, name in watchlist.items():
            quote = quotes.get(code) or {}
            row: dict[str, Any] = {
                "code": code,
                "name": name,
                "price": quote.get("price"),
                "pct_change": quote.get("pct_change"),
            }
            if include_fund_flow and len(code) == 6:
                flow = self.get_fund_flow(code)
                if flow:
                    row["main_net_inflow"] = flow.get("main_net_inflow")
            watchlist_rows.append(row)

        sectors = self.get_sector_rankings()
        return {
            "as_of": datetime.now().isoformat(timespec="seconds"),
            "watchlist": watchlist_rows,
            "sector_top": sectors.get("top", []),
            "sector_bottom": sectors.get("bottom", []),
            "hot_rank_hits": self.get_hot_rank_hits(codes),
            "lhb_hits": self.get_lhb_hits(codes),
            "zt_pool": self.get_zt_pool_summary(),
        }


# ── 표시 헬퍼(순수 함수) ─────────────────────────────

def _fmt_pct(value: Any) -> str:
    number = _safe_float(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _fmt_yi(value: Any) -> str:
    """위안화 금액을 억 단위로 축약."""
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number / 1e8:+.1f}억"


def format_quant_summary(context: dict[str, Any], watchlist: dict[str, str]) -> str:
    """정량 스냅샷을 텔레그램 HTML 본문으로 변환한다."""
    import html as _html

    if not context:
        return ""
    lines: list[str] = []

    rows = context.get("watchlist") or []
    if rows:
        lines.append("<b>관심종목 시세</b>")
        for row in rows:
            name = _html.escape(str(row.get("name") or row.get("code")))
            price = row.get("price")
            price_part = f"{price:,.2f}" if isinstance(price, (int, float)) else "-"
            line = f"• {name} ({row.get('code')}): {price_part} ({_fmt_pct(row.get('pct_change'))})"
            if row.get("main_net_inflow") is not None:
                line += f" 주력 {_fmt_yi(row.get('main_net_inflow'))}"
            lines.append(line)

    sector_top = context.get("sector_top") or []
    sector_bottom = context.get("sector_bottom") or []
    if sector_top or sector_bottom:
        lines.append("")
        lines.append("<b>섹터 온도(동방재부 업종)</b>")
        if sector_top:
            tops = ", ".join(
                f"{_html.escape(s['name'])} {_fmt_pct(s.get('pct_change'))}" for s in sector_top
            )
            lines.append(f"강세: {tops}")
        if sector_bottom:
            bottoms = ", ".join(
                f"{_html.escape(s['name'])} {_fmt_pct(s.get('pct_change'))}" for s in sector_bottom
            )
            lines.append(f"약세: {bottoms}")

    zt_pool = context.get("zt_pool") or {}
    if zt_pool.get("count") is not None:
        lines.append(f"涨停 {zt_pool.get('count', 0)}종목")

    hot_hits = context.get("hot_rank_hits") or []
    if hot_hits:
        hot = ", ".join(
            f"{_html.escape(h['name'] or watchlist.get(h['code'], h['code']))} {h['rank']}위"
            for h in hot_hits
        )
        lines.append(f"인기순위 진입: {hot}")

    lhb_hits = context.get("lhb_hits") or []
    if lhb_hits:
        lines.append("<b>용호방(龙虎榜) 관심종목</b>")
        for hit in lhb_hits[:5]:
            reason = _html.escape(str(hit.get("reason") or "")[:60])
            lines.append(
                f"• {_html.escape(hit['name'] or hit['code'])} ({hit['code']}) {hit.get('date', '')} {reason}"
            )

    return "\n".join(lines).strip()
