from datetime import datetime
from typing import Any

import pandas as pd

from momentum.benchmarks import add_return_columns, latest_rows
from momentum.models import SectorDefinition, StockUniverseEntry, as_float


def _percentile_scores(values: dict[str, float]) -> dict[str, float]:
    clean = {key: value for key, value in values.items() if value == value}
    if not clean:
        return {}
    series = pd.Series(clean, dtype="float64")
    if len(series) == 1:
        return {str(series.index[0]): 50.0}
    ranked = series.rank(pct=True) * 100
    return {str(key): float(value) for key, value in ranked.items()}


def _alert_level(
    total_score: float,
    rs_rank: float,
    market_rs_rank: float,
    turnover_ratio: float,
    breadth_above_ma20: float,
    breadth_outperform_market_20d: float,
    tradable_member_count: int,
    min_sector_member_count: int,
) -> str:
    if tradable_member_count < min_sector_member_count:
        return "No Signal"
    if (
        total_score >= 90
        and rs_rank >= 85
        and market_rs_rank >= 80
        and turnover_ratio >= 1.8
        and breadth_above_ma20 >= 0.70
        and breadth_outperform_market_20d >= 0.60
    ):
        return "Actionable Watch"
    if (
        total_score >= 80
        and rs_rank >= 80
        and turnover_ratio >= 1.5
        and breadth_above_ma20 >= 0.60
    ):
        return "Strong Watch"
    if total_score >= 70 and rs_rank >= 70 and turnover_ratio >= 1.2:
        return "Watch"
    return "No Signal"


def _safe_ratio(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    den = as_float(denominator)
    if den == 0:
        return default
    return as_float(numerator) / den


def _build_stock_candidates(
    latest: pd.DataFrame,
    strong_sector_ids: set[str],
    market_return_20d: float,
    candidate_min_avg_turnover_20d_cny: float,
) -> list[dict[str, Any]]:
    if latest.empty or not strong_sector_ids:
        return []

    strong_ids = [str(x) for x in strong_sector_ids]
    candidates = latest[
        latest["sector_id"].astype(str).isin(strong_ids)
        & (latest["amount_ma20"] >= candidate_min_avg_turnover_20d_cny)
        & (latest["return_20d"] > latest["sector_eq_ret_20d"])
        & (latest["amount_ratio_5d_to_20d"] >= 1.5)
        & (latest["close"] > latest["ma20"])
    ].copy()
    if candidates.empty:
        return []

    candidates["breakout_20d"] = candidates["close"] >= candidates["high20"]
    candidates["breakout_60d"] = candidates["close"] >= candidates["high60"]
    candidates["ma20_gap"] = candidates["close"] / candidates["ma20"].replace(0, pd.NA) - 1
    candidates["overheat_flag"] = (candidates["return_5d"] >= 0.25) | (candidates["ma20_gap"] >= 0.20)
    candidates["limit_up_flag"] = False

    ret_ranks = candidates.groupby("sector_id")["return_20d"].rank(pct=True) * 100
    amount_ranks = candidates.groupby("sector_id")["amount_ratio_5d_to_20d"].rank(pct=True) * 100
    candidates["candidate_score"] = (
        ret_ranks * 0.45
        + amount_ranks * 0.35
        + candidates["breakout_20d"].astype(float) * 10
        + candidates["breakout_60d"].astype(float) * 10
    )

    output: list[dict[str, Any]] = []
    for row in candidates.sort_values("candidate_score", ascending=False).to_dict(orient="records"):
        output.append(
            {
                "trade_date": str(pd.to_datetime(row.get("date")).date()),
                "code": str(row.get("code") or ""),
                "symbol": str(row.get("code") or ""),
                "name": str(row.get("name") or row.get("code") or ""),
                "sector_id": str(row.get("sector_id") or ""),
                "sector_name": str(row.get("sector_name") or ""),
                "ret_5d": as_float(row.get("return_5d")),
                "ret_20d": as_float(row.get("return_20d")),
                "return_20d": as_float(row.get("return_20d")),
                "sector_ret_20d": as_float(row.get("sector_eq_ret_20d")),
                "excess_ret_20d": as_float(row.get("return_20d")) - as_float(row.get("sector_eq_ret_20d")),
                "market_excess_ret_20d": as_float(row.get("return_20d")) - market_return_20d,
                "turnover_ratio_5d_20d": as_float(row.get("amount_ratio_5d_to_20d")),
                "amount_ratio_5d_to_20d": as_float(row.get("amount_ratio_5d_to_20d")),
                "above_ma20": bool(as_float(row.get("close")) > as_float(row.get("ma20"))),
                "above_ma60": bool(as_float(row.get("close")) > as_float(row.get("ma60"))),
                "breakout_20d": bool(row.get("breakout_20d")),
                "breakout_60d": bool(row.get("breakout_60d")),
                "limit_up_flag": bool(row.get("limit_up_flag")),
                "overheat_flag": bool(row.get("overheat_flag")),
                "candidate_score": as_float(row.get("candidate_score")),
            }
        )
    return output


def calculate_scores(
    prices: pd.DataFrame,
    universe: list[StockUniverseEntry],
    sectors: list[SectorDefinition],
    policy_scores: dict[str, float],
    min_result_score: float,
    min_sector_member_count: int = 10,
    min_trading_days_20d: int = 15,
    min_avg_turnover_20d_cny: float = 30_000_000,
    candidate_min_avg_turnover_20d_cny: float = 50_000_000,
) -> dict[str, Any]:
    if prices.empty or not universe or not sectors:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sectors": [],
            "stocks": [],
            "candidates": [],
            "alerts": [],
            "errors": ["가격 데이터 또는 업종 매핑이 없습니다."],
        }

    enriched = add_return_columns(prices)
    latest = latest_rows(enriched)
    if latest.empty:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sectors": [],
            "stocks": [],
            "candidates": [],
            "alerts": [],
            "errors": ["계산 가능한 최신 가격 데이터가 없습니다."],
        }

    meta = pd.DataFrame([entry.__dict__ for entry in universe])
    latest = latest.merge(meta, on="code", how="inner")
    latest["amount_ma20"] = pd.to_numeric(latest["amount_ma20"], errors="coerce").fillna(0.0)
    latest["trading_days_20d"] = pd.to_numeric(latest["trading_days_20d"], errors="coerce").fillna(0.0)
    latest["amount_ratio_5d_to_20d"] = pd.to_numeric(
        latest["amount_ratio_5d_to_20d"],
        errors="coerce",
    ).fillna(0.0)

    tradable = latest[
        (latest["trading_days_20d"] >= min_trading_days_20d)
        & (latest["amount_ma20"] >= min_avg_turnover_20d_cny)
        & latest["return_20d"].notna()
    ].copy()
    if tradable.empty:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sectors": [],
            "stocks": [],
            "candidates": [],
            "alerts": [],
            "errors": ["거래 가능 종목 필터를 통과한 종목이 없습니다."],
        }

    latest_date = pd.to_datetime(tradable["date"].max()).date().isoformat()
    market_return_20d = as_float(tradable["return_20d"].mean())

    sector_defs = {sector.sector_id: sector for sector in sectors}
    raw_sector: dict[str, dict[str, Any]] = {}
    price_metric: dict[str, float] = {}
    price_60_metric: dict[str, float] = {}
    rs_metric: dict[str, float] = {}
    market_rs_metric: dict[str, float] = {}
    volume_metric: dict[str, float] = {}
    breadth20_metric: dict[str, float] = {}
    breadth60_metric: dict[str, float] = {}
    breadth_outperform_metric: dict[str, float] = {}

    for sector_id, group in tradable.groupby("sector_id"):
        sector_id = str(sector_id)
        sector = sector_defs.get(sector_id)
        if sector is None:
            continue
        ex_group = tradable[tradable["sector_id"].astype(str) != sector_id]
        sector_return_5d = as_float(group["return_5d"].mean())
        sector_return_20d = as_float(group["return_20d"].mean())
        sector_return_60d = as_float(group["return_60d"].mean())
        ex_market_return_20d = as_float(ex_group["return_20d"].mean()) if not ex_group.empty else market_return_20d
        ex_rs_20d = sector_return_20d - ex_market_return_20d
        market_rs_20d = sector_return_20d - market_return_20d
        breadth_above_ma20 = as_float((group["close"] > group["ma20"]).mean())
        breadth_above_ma60 = as_float((group["close"] > group["ma60"]).mean())
        breakout_20d = group["close"] >= group["high20"]
        breakout_60d = group["close"] >= group["high60"]
        high20_count = int(breakout_20d.fillna(False).sum())
        high60_count = int(breakout_60d.fillna(False).sum())
        outperform_ratio = as_float((group["return_20d"] > market_return_20d).mean())
        turnover_ratio = as_float(group["amount_ratio_5d_to_20d"].mean(), 1.0)
        tradable_member_count = int(group["code"].nunique())
        member_count = int(latest[latest["sector_id"].astype(str) == sector_id]["code"].nunique())

        raw_sector[sector_id] = {
            "trade_date": latest_date,
            "sector_id": sector_id,
            "industry_code": sector_id,
            "sector_name": sector.sector_name,
            "industry_name": sector.sector_name,
            "sector_return_method": "equal_weight_members",
            "stock_count": member_count,
            "member_count": member_count,
            "tradable_member_count": tradable_member_count,
            "sector_return_5d": sector_return_5d,
            "sector_return_20d": sector_return_20d,
            "sector_return_60d": sector_return_60d,
            "ret_5d": sector_return_5d,
            "ret_20d": sector_return_20d,
            "ret_60d": sector_return_60d,
            "eq_ret_5d": sector_return_5d,
            "eq_ret_20d": sector_return_20d,
            "eq_ret_60d": sector_return_60d,
            "market_equal_weight_return_20d": market_return_20d,
            "ex_sector_market_return_20d": ex_market_return_20d,
            "ex_sector_relative_strength_20d": ex_rs_20d,
            "ex_sector_rs_20d": ex_rs_20d,
            "equal_market_rs_20d": market_rs_20d,
            "above_ma20_ratio": breadth_above_ma20,
            "above_ma60_ratio": breadth_above_ma60,
            "breadth_above_ma20": breadth_above_ma20,
            "breadth_above_ma60": breadth_above_ma60,
            "breadth_outperform_market_20d": outperform_ratio,
            "high20_ratio": _safe_ratio(high20_count, tradable_member_count),
            "new_high_20d_count": high20_count,
            "new_high_60d_count": high60_count,
            "outperform_market_ratio": outperform_ratio,
            "turnover_ratio_5d_20d": turnover_ratio,
            "amount_ratio_5d_to_20d": turnover_ratio,
            "policy_score": float(policy_scores.get(sector_id, 50.0)),
        }
        price_metric[sector_id] = sector_return_20d
        price_60_metric[sector_id] = sector_return_60d
        rs_metric[sector_id] = ex_rs_20d
        market_rs_metric[sector_id] = market_rs_20d
        volume_metric[sector_id] = turnover_ratio
        breadth20_metric[sector_id] = breadth_above_ma20
        breadth60_metric[sector_id] = breadth_above_ma60
        breadth_outperform_metric[sector_id] = outperform_ratio

    price_20_scores = _percentile_scores(price_metric)
    price_60_scores = _percentile_scores(price_60_metric)
    rs_scores = _percentile_scores(rs_metric)
    market_rs_scores = _percentile_scores(market_rs_metric)
    volume_scores = _percentile_scores(volume_metric)
    breadth20_scores = _percentile_scores(breadth20_metric)
    breadth60_scores = _percentile_scores(breadth60_metric)
    breadth_outperform_scores = _percentile_scores(breadth_outperform_metric)

    results: list[dict[str, Any]] = []
    strong_sector_ids: set[str] = set()
    for sector_id, item in raw_sector.items():
        price_score = price_20_scores.get(sector_id, 0.0) * 0.60 + price_60_scores.get(sector_id, 0.0) * 0.40
        relative_strength_score = rs_scores.get(sector_id, 0.0) * 0.70 + market_rs_scores.get(sector_id, 0.0) * 0.30
        breadth_score = (
            breadth20_scores.get(sector_id, 0.0) * 0.40
            + breadth60_scores.get(sector_id, 0.0) * 0.30
            + breadth_outperform_scores.get(sector_id, 0.0) * 0.30
        )
        volume_score = volume_scores.get(sector_id, 0.0)
        total_score = (
            price_score * 0.30
            + relative_strength_score * 0.30
            + volume_score * 0.20
            + breadth_score * 0.20
        )
        rs_rank = rs_scores.get(sector_id, 0.0)
        market_rs_rank = market_rs_scores.get(sector_id, 0.0)
        level = _alert_level(
            total_score,
            rs_rank,
            market_rs_rank,
            as_float(item["turnover_ratio_5d_20d"]),
            as_float(item["breadth_above_ma20"]),
            as_float(item["breadth_outperform_market_20d"]),
            int(item["tradable_member_count"]),
            min_sector_member_count,
        )
        item["price_score"] = float(price_score)
        item["relative_strength_score"] = float(relative_strength_score)
        item["ex_sector_rs_score"] = float(rs_rank)
        item["equal_weight_breadth_score"] = float(breadth_score)
        item["breadth_score"] = float(breadth_score)
        item["volume_score"] = float(volume_score)
        item["score_total"] = float(total_score)
        item["total_score"] = float(total_score)
        item["rs_rank"] = float(rs_rank)
        item["market_rs_rank"] = float(market_rs_rank)
        item["alert_level"] = level
        item["grade"] = level
        item["coverage"] = "OK" if item["tradable_member_count"] >= min_sector_member_count else "Low Coverage"
        if level in {"Strong Watch", "Actionable Watch"}:
            strong_sector_ids.add(sector_id)
        if total_score >= min_result_score:
            results.append(item)

    sector_ret_by_id = {item["sector_id"]: item["eq_ret_20d"] for item in raw_sector.values()}
    latest["sector_eq_ret_20d"] = latest["sector_id"].map(sector_ret_by_id).fillna(0.0)

    stocks = []
    for row in latest.sort_values("return_20d", ascending=False).to_dict(orient="records"):
        stocks.append(
            {
                "trade_date": latest_date,
                "code": row["code"],
                "symbol": row["code"],
                "name": row.get("name") or row["code"],
                "sector_id": row.get("sector_id") or "",
                "sector_name": row.get("sector_name") or "",
                "return_20d": as_float(row.get("return_20d")),
                "return_60d": as_float(row.get("return_60d")),
                "amount_ratio_5d_to_20d": as_float(row.get("amount_ratio_5d_to_20d")),
            }
        )

    candidates = _build_stock_candidates(
        latest,
        strong_sector_ids,
        market_return_20d,
        candidate_min_avg_turnover_20d_cny,
    )
    alerts = [
        {
            "trade_date": item["trade_date"],
            "alert_type": "sector",
            "sector_id": item["sector_id"],
            "industry_code": item["sector_id"],
            "alert_level": item["alert_level"],
            "title": f"[{item['alert_level']}] {item['sector_name']} 업종 모멘텀 감지",
            "payload": item,
        }
        for item in results
        if item["alert_level"] != "No Signal"
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": latest_date,
        "market_equal_weight_return_20d": market_return_20d,
        "sectors": sorted(results, key=lambda x: x["total_score"], reverse=True),
        "stocks": stocks,
        "candidates": candidates,
        "alerts": alerts,
        "errors": [],
    }
