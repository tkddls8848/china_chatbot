import sys
import unittest
from pathlib import Path

import pandas as pd

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from momentum.models import SectorDefinition, StockUniverseEntry
from momentum.backtest import build_backtest_snapshot
from momentum.scoring import calculate_scores


class MomentumScoringTest(unittest.TestCase):
    def test_calculate_scores_creates_sector_metrics_and_candidates(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=80)
        rows = []
        universe = []
        sectors = [
            SectorDefinition("robotics", "로봇"),
            SectorDefinition("banks", "은행"),
        ]
        for idx, code in enumerate(["000001", "000002", "000003", "000004"]):
            sector_id = "robotics" if idx < 2 else "banks"
            sector_name = "로봇" if idx < 2 else "은행"
            universe.append(
                StockUniverseEntry(
                    code=code,
                    name=code,
                    market="SZ",
                    sector_id=sector_id,
                    sector_name=sector_name,
                )
            )
            base = 10 + idx
            for day, date in enumerate(dates):
                if code == "000001":
                    drift = 0.30
                elif code == "000002":
                    drift = 0.10
                else:
                    drift = 0.02
                close = base * (1 + drift * day / len(dates))
                amount = 40_000_000
                if sector_id == "robotics":
                    amount = 30_000_000 if day < 75 else 120_000_000
                rows.append(
                    {
                        "date": date,
                        "code": code,
                        "open": close * 0.99,
                        "high": close * 1.01,
                        "low": close * 0.98,
                        "close": close,
                        "volume": 1_000_000,
                        "amount": amount,
                    }
                )

        result = calculate_scores(
            pd.DataFrame(rows),
            universe,
            sectors,
            policy_scores={},
            min_result_score=0,
            min_sector_member_count=1,
            min_avg_turnover_20d_cny=1,
            candidate_min_avg_turnover_20d_cny=1,
        )

        self.assertFalse(result["errors"])
        self.assertEqual(len(result["sectors"]), 2)
        self.assertTrue(result["candidates"])
        top_sector = result["sectors"][0]
        self.assertIn("total_score", top_sector)
        self.assertIn(top_sector["alert_level"], {"No Signal", "Watch", "Strong Watch", "Actionable Watch"})

        backtest = build_backtest_snapshot(
            pd.DataFrame(rows),
            universe,
            sectors,
            min_avg_turnover_20d_cny=1,
        )
        self.assertIn("signals", backtest)
        self.assertIn("summary", backtest)


if __name__ == "__main__":
    unittest.main()
