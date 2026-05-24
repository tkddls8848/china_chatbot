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
            data_dir=data_dir,
        )
