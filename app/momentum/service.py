from datetime import datetime, timedelta
from typing import Any

from momentum.policy import load_policy_keyword_scores
from momentum.prices import refresh_price_cache
from momentum.scoring import calculate_scores
from momentum.sectors import build_universe, load_sector_definitions
from momentum.settings import MomentumSettings
from momentum.store import MomentumStore
from stock_db import StockDatabase


class MomentumService:
    def __init__(self, settings: MomentumSettings, stock_db: StockDatabase):
        self.settings = settings
        self.stock_db = stock_db
        self.store = MomentumStore(settings.data_dir)

    def get_last_result(self) -> dict[str, Any] | None:
        state = self.store.load_state()
        result = state.get("last_result")
        return result if isinstance(result, dict) else None

    def refresh(self, force: bool = False) -> dict[str, Any]:
        if not self.settings.enabled:
            return {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "sectors": [],
                "stocks": [],
                "errors": ["MOMENTUM_ENABLED=false 상태입니다."],
            }

        state = self.store.load_state()
        state["last_requested_at"] = datetime.now().isoformat(timespec="seconds")
        if not force and self._is_cooldown_active(state):
            cached = state.get("last_result")
            if isinstance(cached, dict):
                cached = dict(cached)
                cached.setdefault("errors", [])
                cached["cache_status"] = "cooldown_cached"
                self.store.save_state(state)
                return cached

        sectors = load_sector_definitions(self.store)
        universe = build_universe(self.stock_db, sectors)
        price_cache = self.store.load_price_cache()
        prices, failures = refresh_price_cache(
            price_cache,
            universe,
            self.settings.price_lookback_days,
            self.settings.price_fetch_delay_seconds,
        )
        if not prices.empty:
            self.store.save_price_cache(prices)

        policy_scores = load_policy_keyword_scores(
            self.store,
            sectors,
            self.settings.use_policy_score,
        )
        result = calculate_scores(
            prices,
            universe,
            sectors,
            policy_scores,
            self.settings.min_result_score,
        )
        if failures:
            result.setdefault("errors", [])
            result["errors"].append(f"가격 수집 실패 종목 {len(failures)}개")
        result["universe_count"] = len(universe)
        result["sector_count"] = len(sectors)
        result["cache_status"] = "refreshed"

        state["last_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_result"] = result
        self.store.save_state(state)
        return result

    def _is_cooldown_active(self, state: dict[str, Any]) -> bool:
        raw = state.get("last_refreshed_at")
        if not raw:
            return False
        try:
            last = datetime.fromisoformat(str(raw))
        except ValueError:
            return False
        return datetime.now() - last < timedelta(minutes=self.settings.refresh_cooldown_minutes)
