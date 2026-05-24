import pandas as pd


def add_return_columns(prices: pd.DataFrame, periods: tuple[int, ...] = (5, 20, 60)) -> pd.DataFrame:
    if prices.empty:
        return prices
    df = prices.sort_values(["code", "date"]).copy()
    for period in periods:
        df[f"return_{period}d"] = df.groupby("code")["close"].pct_change(period)
    df["ma20"] = df.groupby("code")["close"].transform(lambda s: s.rolling(20).mean())
    df["ma60"] = df.groupby("code")["close"].transform(lambda s: s.rolling(60).mean())
    df["high20"] = df.groupby("code")["close"].transform(lambda s: s.rolling(20).max())
    df["amount_ma20"] = df.groupby("code")["amount"].transform(lambda s: s.rolling(20).mean())
    df["amount_ma5"] = df.groupby("code")["amount"].transform(lambda s: s.rolling(5).mean())
    return df


def latest_rows(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    idx = prices.sort_values(["code", "date"]).groupby("code").tail(1).index
    return prices.loc[idx].copy()
