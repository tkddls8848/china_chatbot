import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MomentumSettings:
    enabled: bool
    top_limit: int
    min_result_score: float
    price_lookback_days: int
    use_policy_score: bool
    refresh_cooldown_minutes: int
    price_fetch_delay_seconds: float
    price_max_consecutive_failures: int
    sector_top_n_per_sector: int
    min_sector_member_count: int
    min_trading_days_20d: int
    min_avg_turnover_20d_cny: float
    candidate_min_avg_turnover_20d_cny: float
    duplicate_alert_suppression_days: int
    data_dir: Path

    @classmethod
    def from_env(cls, base_dir: Path) -> "MomentumSettings":
        data_dir = Path(os.environ.get("MOMENTUM_DATA_DIR", "data/momentum"))
        if not data_dir.is_absolute():
            data_dir = base_dir / data_dir
        return cls(
            enabled=os.environ.get("MOMENTUM_ENABLED", "true").lower() == "true",
            top_limit=int(os.environ.get("MOMENTUM_TOP_LIMIT", "10")),
            min_result_score=float(os.environ.get("MOMENTUM_MIN_RESULT_SCORE", "0")),
            price_lookback_days=int(os.environ.get("MOMENTUM_PRICE_LOOKBACK_DAYS", "160")),
            use_policy_score=os.environ.get("MOMENTUM_USE_POLICY_SCORE", "true").lower() == "true",
            refresh_cooldown_minutes=int(os.environ.get("MOMENTUM_REFRESH_COOLDOWN_MINUTES", "10")),
            price_fetch_delay_seconds=float(os.environ.get("MOMENTUM_PRICE_FETCH_DELAY_SECONDS", "0.8")),
            price_max_consecutive_failures=int(os.environ.get("MOMENTUM_PRICE_MAX_CONSECUTIVE_FAILURES", "5")),
            sector_top_n_per_sector=int(os.environ.get("MOMENTUM_SECTOR_TOP_N_PER_SECTOR", "20")),
            min_sector_member_count=int(os.environ.get("MOMENTUM_MIN_SECTOR_MEMBER_COUNT", "10")),
            min_trading_days_20d=int(os.environ.get("MOMENTUM_MIN_TRADING_DAYS_20D", "15")),
            min_avg_turnover_20d_cny=float(os.environ.get("MOMENTUM_MIN_AVG_TURNOVER_20D_CNY", "30000000")),
            candidate_min_avg_turnover_20d_cny=float(os.environ.get("MOMENTUM_CANDIDATE_MIN_AVG_TURNOVER_20D_CNY", "50000000")),
            duplicate_alert_suppression_days=int(os.environ.get("MOMENTUM_DUPLICATE_ALERT_SUPPRESSION_DAYS", "5")),
            data_dir=data_dir,
        )
