from datetime import datetime, timedelta
from typing import Any

from momentum.backtest import build_backtest_snapshot
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
        universe = build_universe(
            self.stock_db,
            sectors,
            top_n=self.settings.sector_top_n_per_sector,
        )
        price_cache = self.store.load_price_cache()
        prices, failures = refresh_price_cache(
            price_cache,
            universe,
            self.settings.price_lookback_days,
            self.settings.price_fetch_delay_seconds,
            self.settings.price_max_consecutive_failures,
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
            self.settings.min_sector_member_count,
            self.settings.min_trading_days_20d,
            self.settings.min_avg_turnover_20d_cny,
            self.settings.candidate_min_avg_turnover_20d_cny,
        )
        if failures:
            result.setdefault("errors", [])
            result["errors"].append(f"가격 수집 실패 종목 {len(failures)}개")
        result["universe_count"] = len(universe)
        result["sector_count"] = len(sectors)
        result["cache_status"] = "refreshed"
        result["backtest"] = build_backtest_snapshot(
            prices,
            universe,
            sectors,
            self.settings.min_trading_days_20d,
            self.settings.min_avg_turnover_20d_cny,
        )
        result["alerts"] = self._filter_duplicate_alerts(state, result.get("alerts") or [])

        state["last_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_result"] = result
        state["alert_history"] = self._updated_alert_history(
            state.get("alert_history"),
            result.get("alerts") or [],
        )
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

    def _filter_duplicate_alerts(
        self,
        state: dict[str, Any],
        alerts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        history = state.get("alert_history")
        if not isinstance(history, list):
            return alerts

        cutoff = datetime.now() - timedelta(days=self.settings.duplicate_alert_suppression_days)
        recent_keys = set()
        for item in history:
            if not isinstance(item, dict):
                continue
            raw_sent_at = item.get("sent_at") or item.get("created_at")
            try:
                sent_at = datetime.fromisoformat(str(raw_sent_at))
            except (TypeError, ValueError):
                continue
            if sent_at < cutoff:
                continue
            recent_keys.add((item.get("alert_type"), item.get("sector_id"), item.get("alert_level")))

        filtered = []
        for alert in alerts:
            key = (alert.get("alert_type"), alert.get("sector_id"), alert.get("alert_level"))
            if key in recent_keys:
                alert = dict(alert)
                alert["suppressed"] = True
            filtered.append(alert)
        return filtered

    @staticmethod
    def _updated_alert_history(
        history: Any,
        alerts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing = history if isinstance(history, list) else []
        now = datetime.now().isoformat(timespec="seconds")
        additions = []
        for alert in alerts:
            if alert.get("suppressed"):
                continue
            additions.append(
                {
                    "created_at": now,
                    "sent_at": now,
                    "trade_date": alert.get("trade_date"),
                    "alert_type": alert.get("alert_type"),
                    "sector_id": alert.get("sector_id"),
                    "alert_level": alert.get("alert_level"),
                    "title": alert.get("title"),
                }
            )
        return (existing + additions)[-200:]
