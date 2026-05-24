from datetime import datetime
from typing import Any

import pandas as pd

from momentum.benchmarks import add_return_columns, latest_rows
from momentum.models import SectorDefinition, StockUniverseEntry, as_float


def _rank_score(values: dict[str, float]) -> dict[str, float]:
    clean = {key: value for key, value in values.items() if value == value}
    if not clean:
        return {}
    series = pd.Series(clean)
    if len(series) == 1:
        return {str(series.index[0]): 50.0}
    ranked = series.rank(pct=True) * 100
    return {str(key): float(value) for key, value in ranked.items()}


def _grade(score: float) -> str:
    if score >= 80:
        return "Actionable Watch"
    if score >= 65:
        return "Strong Watch"
    if score >= 50:
        return "Watch"
    return "No Signal"


def calculate_scores(
    prices: pd.DataFrame,
    universe: list[StockUniverseEntry],
    sectors: list[SectorDefinition],
    policy_scores: dict[str, float],
    min_result_score: float,
) -> dict[str, Any]:
    if prices.empty or not universe or not sectors:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sectors": [],
            "stocks": [],
            "errors": ["가격 데이터 또는 업종 매핑이 없습니다."],
        }

    enriched = add_return_columns(prices)
    latest = latest_rows(enriched)
    if latest.empty:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sectors": [],
            "stocks": [],
            "errors": ["계산 가능한 최신 가격 데이터가 없습니다."],
        }

    meta = pd.DataFrame([entry.__dict__ for entry in universe])
    latest = latest.merge(meta, on="code", how="inner")
    market_return_20d = as_float(latest["return_20d"].mean())

    sector_defs = {sector.sector_id: sector for sector in sectors}
    raw_sector: dict[str, dict[str, Any]] = {}
    price_metric: dict[str, float] = {}
    rs_metric: dict[str, float] = {}

    for sector_id, group in latest.groupby("sector_id"):
        sector = sector_defs.get(str(sector_id))
        if sector is None:
            continue
        ex_group = latest[latest["sector_id"] != sector_id]
        sector_return_5d = as_float(group["return_5d"].mean())
        sector_return_20d = as_float(group["return_20d"].mean())
        sector_return_60d = as_float(group["return_60d"].mean())
        ex_market_return_20d = as_float(ex_group["return_20d"].mean()) if not ex_group.empty else market_return_20d
        ex_rs_20d = sector_return_20d - ex_market_return_20d
        above_ma20 = as_float((group["close"] > group["ma20"]).mean())
        above_ma60 = as_float((group["close"] > group["ma60"]).mean())
        high20_ratio = as_float((group["close"] >= group["high20"]).mean())
        outperform_ratio = as_float((group["return_20d"] > market_return_20d).mean())
        amount_ratio = as_float((group["amount_ma5"] / group["amount_ma20"]).replace([float("inf")], pd.NA).mean(), 1.0)
        amount_increase_ratio = as_float((group["amount_ma5"] > group["amount_ma20"]).mean())

        raw_sector[str(sector_id)] = {
            "sector_id": str(sector_id),
            "sector_name": sector.sector_name,
            "stock_count": int(group["code"].nunique()),
            "sector_return_5d": sector_return_5d,
            "sector_return_20d": sector_return_20d,
            "sector_return_60d": sector_return_60d,
            "market_equal_weight_return_20d": market_return_20d,
            "ex_sector_market_return_20d": ex_market_return_20d,
            "ex_sector_relative_strength_20d": ex_rs_20d,
            "above_ma20_ratio": above_ma20,
            "above_ma60_ratio": above_ma60,
            "high20_ratio": high20_ratio,
            "outperform_market_ratio": outperform_ratio,
            "amount_ratio_5d_to_20d": amount_ratio,
            "amount_increase_ratio": amount_increase_ratio,
            "policy_score": float(policy_scores.get(str(sector_id), 50.0)),
        }
        price_metric[str(sector_id)] = (sector_return_20d * 0.7) + (sector_return_60d * 0.3)
        rs_metric[str(sector_id)] = ex_rs_20d

    price_scores = _rank_score(price_metric)
    rs_scores = _rank_score(rs_metric)
    results: list[dict[str, Any]] = []
    for sector_id, item in raw_sector.items():
        breadth_score = (
            item["above_ma20_ratio"] * 35
            + item["above_ma60_ratio"] * 20
            + item["outperform_market_ratio"] * 30
            + item["high20_ratio"] * 15
        )
        volume_score = min(max(item["amount_ratio_5d_to_20d"] / 2.5 * 100, 0), 100)
        item["price_score"] = price_scores.get(sector_id, 0.0)
        item["ex_sector_rs_score"] = rs_scores.get(sector_id, 0.0)
        item["equal_weight_breadth_score"] = float(breadth_score)
        item["volume_score"] = float(volume_score)
        total_score = (
            item["price_score"] * 0.25
            + item["ex_sector_rs_score"] * 0.25
            + item["equal_weight_breadth_score"] * 0.20
            + item["volume_score"] * 0.15
            + item["policy_score"] * 0.15
        )
        item["total_score"] = float(total_score)
        item["grade"] = _grade(total_score)
        item["coverage"] = "OK" if item["stock_count"] >= 8 else "Low Coverage"
        if total_score >= min_result_score:
            results.append(item)

    stocks = []
    for row in latest.to_dict(orient="records"):
        stocks.append(
            {
                "code": row["code"],
                "name": row.get("name") or row["code"],
                "sector_id": row.get("sector_id") or "",
                "sector_name": row.get("sector_name") or "",
                "return_20d": as_float(row.get("return_20d")),
                "return_60d": as_float(row.get("return_60d")),
                "amount_ratio_5d_to_20d": as_float(row.get("amount_ma5")) / max(as_float(row.get("amount_ma20")), 1e-9),
            }
        )

    scored_ids = {item["sector_id"] for item in results}
    for sector in sectors:
        if sector.sector_id in scored_ids:
            continue
        policy_score = float(policy_scores.get(sector.sector_id, 50.0))
        total_score = policy_score * 0.15
        item = {
            "sector_id": sector.sector_id,
            "sector_name": sector.sector_name,
            "stock_count": 0,
            "sector_return_5d": None,
            "sector_return_20d": None,
            "sector_return_60d": None,
            "market_equal_weight_return_20d": market_return_20d,
            "ex_sector_market_return_20d": None,
            "ex_sector_relative_strength_20d": None,
            "above_ma20_ratio": None,
            "above_ma60_ratio": None,
            "high20_ratio": None,
            "outperform_market_ratio": None,
            "amount_ratio_5d_to_20d": None,
            "amount_increase_ratio": None,
            "policy_score": policy_score,
            "price_score": 0.0,
            "ex_sector_rs_score": 0.0,
            "equal_weight_breadth_score": 0.0,
            "volume_score": 0.0,
            "total_score": total_score,
            "grade": "No Data",
            "coverage": "No Data",
        }
        if total_score >= min_result_score:
            results.append(item)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market_equal_weight_return_20d": market_return_20d,
        "sectors": sorted(results, key=lambda x: x["total_score"], reverse=True),
        "stocks": sorted(stocks, key=lambda x: x["return_20d"], reverse=True),
        "errors": [],
    }
