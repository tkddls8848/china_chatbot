import logging
import time
from datetime import datetime, timedelta
from http.client import RemoteDisconnected

import akshare as ak
import pandas as pd
import requests
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from momentum.models import StockUniverseEntry

logger = logging.getLogger(__name__)

NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
    RemoteDisconnected,
)


def _retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(NETWORK_ERRORS),
        reraise=True,
    )(func)


def _yf_symbol(code: str) -> str:
    # 앱 내부 5자리 HK 코드(00700) → Yahoo Finance 형식(0700.HK)
    return f"{int(code):04d}.HK"


def _yyyymmdd_to_iso(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


@_retry_on_network
def _fetch_hist_yfinance(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    raw = yf.Ticker(_yf_symbol(code)).history(
        start=_yyyymmdd_to_iso(start_date),
        end=_yyyymmdd_to_iso(end_date),
        auto_adjust=True,
    )
    if raw.empty:
        return pd.DataFrame()
    df = raw.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df["code"] = code
    df["amount"] = df["close"] * df["volume"]
    return df[["date", "code", "open", "high", "low", "close", "volume", "amount"]].dropna(subset=["date", "close"])


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
    date_col = _pick_column(df, ["\u65e5\u671f", "date"], 0)
    open_col = _pick_column(df, ["\u5f00\u76d8", "open"], 1)
    close_col = _pick_column(df, ["\u6536\u76d8", "close"], 2)
    high_col = _pick_column(df, ["\u6700\u9ad8", "high"], 3)
    low_col = _pick_column(df, ["\u6700\u4f4e", "low"], 4)
    volume_col = _pick_column(df, ["\u6210\u4ea4\u91cf", "volume"], 5)
    amount_col = _pick_column(df, ["\u6210\u4ea4\u989d", "amount"], 6)
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
    max_consecutive_failures: int = 5,
) -> tuple[pd.DataFrame, list[str]]:
    end = datetime.now()
    start = end - timedelta(days=max(lookback_days * 2, 260))
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    frames = [cache] if not cache.empty else []
    failures: list[str] = []
    failure_log_limit = 3

    unique_entries: list[StockUniverseEntry] = []
    seen_codes: set[str] = set()
    for entry in universe:
        if entry.code in seen_codes:
            continue
        seen_codes.add(entry.code)
        unique_entries.append(entry)

    consecutive_network_failures = 0
    for index, entry in enumerate(unique_entries):
        if max_consecutive_failures > 0 and consecutive_network_failures >= max_consecutive_failures:
            skipped = [item.code for item in unique_entries[index:]]
            failures.extend(skipped)
            logger.warning(
                "[Momentum] stopping price refresh after %d consecutive network failures; skipped %d symbols and will use cache where available",
                consecutive_network_failures,
                len(skipped),
            )
            break

        try:
            if entry.market == "HK":
                normalized = _fetch_hist_yfinance(entry.code, start_date, end_date)
            else:
                raw = _fetch_hist(entry.code, start_date, end_date)
                normalized = _normalize_hist(raw, entry.code)
            if normalized.empty:
                failures.append(entry.code)
                consecutive_network_failures = 0
                continue
            frames.append(normalized)
            consecutive_network_failures = 0
        except NETWORK_ERRORS as e:
            failures.append(entry.code)
            consecutive_network_failures += 1
            if len(failures) <= failure_log_limit:
                logger.warning("[Momentum] price fetch failed for %s (%s): %s", entry.code, type(e).__name__, e)
            elif len(failures) == failure_log_limit + 1:
                logger.warning("[Momentum] additional price fetch failures suppressed until summary")
        except Exception as e:
            failures.append(entry.code)
            consecutive_network_failures = 0
            logger.warning("[Momentum] price fetch failed for %s (%s): %s", entry.code, type(e).__name__, e)
        finally:
            if index < len(unique_entries) - 1 and fetch_delay_seconds > 0:
                time.sleep(fetch_delay_seconds)

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
