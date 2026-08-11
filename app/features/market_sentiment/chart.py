"""Rendering for the Telegram market-sentiment chart."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO


MARKET_LABELS = {
    "CN": "China mainland",
    "HK": "Hong Kong",
    "US": "United States",
    "KR": "Korea",
    "JP": "Japan",
    "EU": "Europe",
    "OTHER": "Other",
}


def market_label(market: str) -> str:
    return MARKET_LABELS.get(market, market)


def _trend_series(points: list[dict]) -> tuple[list[datetime], list[float]]:
    """Convert categorical date strings to sorted date coordinates."""
    parsed = sorted(
        (
            datetime.fromisoformat(str(point["date"])),
            float(point["avg_sentiment"]),
        )
        for point in points
    )
    return [day for day, _ in parsed], [value for _, value in parsed]


def _draw_consensus_panel(axis, consensus: list[dict]) -> None:
    """Draw the Polymarket macro risk-appetite panel on its own axis.

    This is a separate reference line with its own unit (percentage points of
    probability), never merged into the -1..+1 news sentiment scores or the
    country ranking.  It is drawn as discrete daily bars because gaps are real:
    a missing snapshot leaves no bar rather than a line interpolated across it.
    """
    import matplotlib.dates as mdates

    points = sorted(
        (datetime.fromisoformat(str(point["date"])), float(point["change_pp"]))
        for point in consensus
    )
    days = [day for day, _ in points]
    values = [value for _, value in points]
    colors = [
        "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#64748b"
        for value in values
    ]
    axis.bar(days, values, color=colors, width=0.6)
    axis.axhline(0, color="#94a3b8", linewidth=0.9)
    axis.set_title("Polymarket macro risk appetite — 24h probability change")
    axis.set_ylabel("pp")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axis.tick_params(axis="x", rotation=45)
    axis.grid(axis="y", alpha=0.2)


def render_market_chart(
    markets: dict[str, dict],
    lookback_days: int,
    consensus: list[dict] | None = None,
) -> BytesIO:
    """Return a PNG with latest market mood ranking and daily sentiment trends.

    ``consensus`` adds an optional bottom panel.  When it is omitted the figure
    is exactly the two-panel chart it has always been — the Polymarket pilot
    must not change what ``/market`` renders while it is still in shadow mode.
    """
    # Telegram handlers run outside the process main thread.  A GUI backend
    # attempts to create a window there, so force Matplotlib's file-only backend
    # before importing pyplot.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    ordered = sorted(markets.items(), key=lambda item: item[1]["avg_sentiment"], reverse=True)
    labels = [market_label(key) for key, _ in ordered]
    values = [item["avg_sentiment"] for _, item in ordered]
    colors = ["#16a34a" if value > 0.1 else "#dc2626" if value < -0.1 else "#64748b" for value in values]

    if consensus:
        fig = plt.figure(figsize=(12, 7.5))
        grid = fig.add_gridspec(
            2, 2, height_ratios=[1.5, 1.0], width_ratios=[0.9, 1.4]
        )
        ranking_ax = fig.add_subplot(grid[0, 0])
        trend_ax = fig.add_subplot(grid[0, 1])
        consensus_ax = fig.add_subplot(grid[1, :])
        consensus_ax.set_facecolor("#f8fafc")
    else:
        fig, (ranking_ax, trend_ax) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [0.9, 1.4]})
        consensus_ax = None
    fig.patch.set_facecolor("#f8fafc")
    ranking_ax.set_facecolor("#f8fafc")
    trend_ax.set_facecolor("#f8fafc")
    ranking_ax.barh(labels, values, color=colors, height=0.58)
    ranking_ax.axvline(0, color="#94a3b8", linewidth=0.9)
    ranking_ax.set_xlim(-1, 1)
    ranking_ax.set_title("Average news sentiment")
    ranking_ax.set_xlabel("-1 negative     0 neutral     +1 positive")
    ranking_ax.invert_yaxis()
    for index, value in enumerate(values):
        ranking_ax.text(value + (0.03 if value >= 0 else -0.03), index, f"{value:+.2f}", va="center", ha="left" if value >= 0 else "right", fontsize=9)

    for market, stats in ordered:
        dates, sentiments = _trend_series(stats["daily"])
        trend_ax.plot(
            dates,
            sentiments,
            marker="o",
            linewidth=2,
            label=market_label(market),
        )
    trend_ax.axhline(0, color="#94a3b8", linewidth=0.9)
    trend_ax.set_ylim(-1, 1)
    trend_ax.set_title(f"Daily sentiment trend ({lookback_days}d)")
    trend_ax.set_ylabel("Average sentiment")
    trend_ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    trend_ax.tick_params(axis="x", rotation=45)
    trend_ax.legend(loc="best", frameon=False)
    trend_ax.grid(axis="y", alpha=0.2)
    if consensus_ax is not None:
        _draw_consensus_panel(consensus_ax, consensus)
    fig.tight_layout()

    image = BytesIO()
    image.name = "market_sentiment.png"
    fig.savefig(image, format="png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    image.seek(0)
    return image
