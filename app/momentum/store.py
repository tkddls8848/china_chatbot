import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class MomentumStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sector_map_file = self.data_dir / "sector_map.json"
        self.industry_keywords_file = self.data_dir / "industry_keywords.json"
        self.price_cache_file = self.data_dir / "price_cache.json"
        self.state_file = self.data_dir / "momentum_state.json"

    def read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_price_cache(self) -> pd.DataFrame:
        data = self.read_json(self.price_cache_file, [])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.dropna(subset=["date", "code", "close"])

    def save_price_cache(self, df: pd.DataFrame) -> None:
        if df.empty:
            self.write_json(self.price_cache_file, [])
            return
        normalized = df.copy()
        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        normalized = normalized.dropna(subset=["date", "code"]).sort_values(["code", "date"])
        records = normalized.to_dict(orient="records")
        self.write_json(self.price_cache_file, records)

    def load_state(self) -> dict[str, Any]:
        return self.read_json(
            self.state_file,
            {
                "last_refreshed_at": None,
                "last_requested_at": None,
                "last_result": None,
                "alert_history": [],
            },
        )

    def save_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.write_json(self.state_file, state)
