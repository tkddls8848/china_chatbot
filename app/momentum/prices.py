import logging
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from momentum.models import StockUniverseEntry

logger = logging.getLogger(__name__)


def _retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError, TimeoutError)),
        reraise=True,
    )(func)


@_retry_on_network
def _fetch_hist(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    return ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )


def _pick_column(df: pd.DataFrame, candidates: list[str], fallback: int | None = None) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    if fallback is not None and fallback < len(df.columns):
        return str(df.columns[fallback])
    return None


def _normalize_hist(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    date_col = _pick_column(df, ["日期", "date"], 0)
    open_col = _pick_column(df, ["开盘", "open"], 1)
    close_col = _pick_column(df, ["收盘", "close"], 2)
    high_col = _pick_column(df, ["最高", "high"], 3)
    low_col = _pick_column(df, ["最低", "low"], 4)
    volume_col = _pick_column(df, ["成交量", "volume"], 5)
    amount_col = _pick_column(df, ["成交额", "amount"], 6)
    if not date_col or not close_col:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "code": code,
            "open": pd.to_numeric(df[open_col], errors="coerce") if open_col else 0.0,
            "high": pd.to_numeric(df[high_col], errors="coerce") if high_col else 0.0,
            "low": pd.to_numeric(df[low_col], errors="coerce") if low_col else 0.0,
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": pd.to_numeric(df[volume_col], errors="coerce") if volume_col else 0.0,
            "amount": pd.to_numeric(df[amount_col], errors="coerce") if amount_col else 0.0,
        }
    )
    return out.dropna(subset=["date", "close"])


def refresh_price_cache(
    cache: pd.DataFrame,
    universe: list[StockUniverseEntry],
    lookback_days: int,
    fetch_delay_seconds: float = 0.8,
) -> tuple[pd.DataFrame, list[str]]:
    end = datetime.now()
    start = end - timedelta(days=max(lookback_days * 2, 260))
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    frames = [cache] if not cache.empty else []
    failures: list[str] = []

    seen_codes: set[str] = set()
    fetched_count = 0
    for entry in universe:
        if entry.code in seen_codes:
            continue
        seen_codes.add(entry.code)
        if fetched_count and fetch_delay_seconds > 0:
            time.sleep(fetch_delay_seconds)
        try:
            raw = _fetch_hist(entry.code, start_date, end_date)
            normalized = _normalize_hist(raw, entry.code)
            if normalized.empty:
                failures.append(entry.code)
                continue
            frames.append(normalized)
            fetched_count += 1
        except Exception as e:
            failures.append(entry.code)
            logger.warning("[Momentum] price fetch failed for %s (%s): %s", entry.code, type(e).__name__, e)

    if failures:
        logger.warning(
            "[Momentum] price fetch failed for %d/%d symbols. Examples: %s",
            len(failures),
            len(seen_codes),
            ", ".join(failures[:5]),
        )

    if not frames:
        return pd.DataFrame(), failures

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["date", "code", "close"])
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.drop_duplicates(["code", "date"], keep="last")
    cutoff = pd.Timestamp(end - timedelta(days=max(lookback_days * 2, 260)))
    merged = merged[merged["date"] >= cutoff]
    return merged.sort_values(["code", "date"]).reset_index(drop=True), failures
