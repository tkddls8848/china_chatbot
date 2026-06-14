import pandas as pd


def add_return_columns(prices: pd.DataFrame, periods: tuple[int, ...] = (5, 20, 60)) -> pd.DataFrame:
    if prices.empty:
        return prices
    df = prices.sort_values(["code", "date"]).copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
    df["close"] = pd.to_numeric(df.get("close", 0.0), errors="coerce")
    for period in periods:
        df[f"return_{period}d"] = df.groupby("code")["close"].pct_change(period)
    df["ma20"] = df.groupby("code")["close"].transform(lambda s: s.rolling(20).mean())
    df["ma60"] = df.groupby("code")["close"].transform(lambda s: s.rolling(60).mean())
    df["high20"] = df.groupby("code")["close"].transform(lambda s: s.rolling(20).max())
    df["high60"] = df.groupby("code")["close"].transform(lambda s: s.rolling(60).max())
    df["amount_ma20"] = df.groupby("code")["amount"].transform(lambda s: s.rolling(20).mean())
    df["amount_ma5"] = df.groupby("code")["amount"].transform(lambda s: s.rolling(5).mean())
    df["trading_days_20d"] = df.groupby("code")["close"].transform(lambda s: s.rolling(20).count())
    df["amount_ratio_5d_to_20d"] = df["amount_ma5"] / df["amount_ma20"].replace(0, pd.NA)
    return df


def latest_rows(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    idx = prices.sort_values(["code", "date"]).groupby("code").tail(1).index
    return prices.loc[idx].copy()
