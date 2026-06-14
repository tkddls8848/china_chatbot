from typing import Any

import pandas as pd

from momentum.benchmarks import add_return_columns
from momentum.models import SectorDefinition, StockUniverseEntry, as_float


def build_backtest_snapshot(
    prices: pd.DataFrame,
    universe: list[StockUniverseEntry],
    sectors: list[SectorDefinition],
    min_trading_days_20d: int = 15,
    min_avg_turnover_20d_cny: float = 30_000_000,
    max_signals: int = 200,
) -> dict[str, Any]:
    if prices.empty or not universe or not sectors:
        return {"signals": 0, "summary": {}, "errors": ["백테스트용 데이터가 부족합니다."]}

    df = add_return_columns(prices)
    df = df.sort_values(["code", "date"]).copy()
    for period in (5, 10, 20):
        df[f"forward_{period}d"] = df.groupby("code")["close"].shift(-period) / df["close"] - 1

    meta = pd.DataFrame([entry.__dict__ for entry in universe])
    df = df.merge(meta, on="code", how="inner")
    df = df[
        (df["trading_days_20d"] >= min_trading_days_20d)
        & (df["amount_ma20"] >= min_avg_turnover_20d_cny)
        & df["return_20d"].notna()
        & df["forward_20d"].notna()
    ].copy()
    if df.empty:
        return {"signals": 0, "summary": {}, "errors": ["백테스트 필터를 통과한 데이터가 없습니다."]}

    sector_names = {sector.sector_id: sector.sector_name for sector in sectors}
    rows: list[dict[str, Any]] = []
    for date, day in df.groupby("date"):
        market_ret_20d = as_float(day["return_20d"].mean())
        market_fwd = {
            period: as_float(day[f"forward_{period}d"].mean())
            for period in (5, 10, 20)
        }
        sector_rows = []
        for sector_id, group in day.groupby("sector_id"):
            sector_id = str(sector_id)
            ex_group = day[day["sector_id"].astype(str) != sector_id]
            if ex_group.empty:
                continue
            ex_rs_20d = as_float(group["return_20d"].mean()) - as_float(ex_group["return_20d"].mean())
            sector_rows.append(
                {
                    "trade_date": str(pd.to_datetime(date).date()),
                    "sector_id": sector_id,
                    "sector_name": sector_names.get(sector_id, sector_id),
                    "ex_rs_20d": ex_rs_20d,
                    "ret_20d": as_float(group["return_20d"].mean()),
                    "member_count": int(group["code"].nunique()),
                    "forward_excess_5d": as_float(group["forward_5d"].mean()) - market_fwd[5],
                    "forward_excess_10d": as_float(group["forward_10d"].mean()) - market_fwd[10],
                    "forward_excess_20d": as_float(group["forward_20d"].mean()) - market_fwd[20],
                    "market_ret_20d": market_ret_20d,
                }
            )
        if not sector_rows:
            continue
        ranked = pd.DataFrame(sector_rows)
        ranked["rs_rank"] = ranked["ex_rs_20d"].rank(pct=True) * 100
        signals = ranked[ranked["rs_rank"] >= 80].sort_values("rs_rank", ascending=False)
        rows.extend(signals.to_dict(orient="records"))

    if not rows:
        return {"signals": 0, "summary": {}, "errors": []}

    signals_df = pd.DataFrame(rows).tail(max_signals)
    summary = {
        "avg_forward_excess_5d": as_float(signals_df["forward_excess_5d"].mean()),
        "avg_forward_excess_10d": as_float(signals_df["forward_excess_10d"].mean()),
        "avg_forward_excess_20d": as_float(signals_df["forward_excess_20d"].mean()),
        "positive_ratio_10d": as_float((signals_df["forward_excess_10d"] > 0).mean()),
        "positive_ratio_20d": as_float((signals_df["forward_excess_20d"] > 0).mean()),
    }
    return {
        "signals": int(len(signals_df)),
        "summary": summary,
        "recent_signals": signals_df.tail(20).to_dict(orient="records"),
        "errors": [],
    }
