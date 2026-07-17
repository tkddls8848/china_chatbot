"""전송한 뉴스의 감성·관련종목 로그.

마감 브리핑의 관심종목별 감성 집계에 쓰인다. retention_days 이전 항목은
자동 만료된다.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class NewsLog:
    def __init__(self, file_path: Path, retention_days: int = 3):
        self._file_path = file_path
        self._retention_days = max(1, retention_days)
        self._entries: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._load()

    def _cutoff(self) -> datetime:
        return datetime.now() - timedelta(days=self._retention_days)

    def _evict(self) -> None:
        cutoff = self._cutoff()
        kept = []
        for entry in self._entries:
            try:
                if datetime.fromisoformat(str(entry.get("ts"))) >= cutoff:
                    kept.append(entry)
            except (TypeError, ValueError):
                continue
        self._entries = kept

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(raw, list):
            self._entries = [e for e in raw if isinstance(e, dict)]
            self._evict()

    async def record(
        self,
        source: str,
        title: str,
        sentiment: float | None,
        impact: str,
        codes: list[str],
        market: str = "OTHER",
        article_id: str = "",
        occurred_at: datetime | None = None,
    ) -> bool:
        async with self._lock:
            normalized_id = str(article_id).strip()
            if normalized_id and any(entry.get("article_id") == normalized_id for entry in self._entries):
                return False
            self._entries.append(
                {
                    "ts": (occurred_at or datetime.now()).isoformat(timespec="seconds"),
                    "source": source,
                    "article_id": normalized_id,
                    "title": title[:120],
                    "sentiment": sentiment,
                    "impact": impact,
                    "codes": list(codes),
                    "market": str(market or "OTHER").strip().upper(),
                }
            )
            self._evict()
            data = json.dumps(self._entries, ensure_ascii=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")
            return True

    async def snapshot(self, since_hours: int = 24) -> list[dict[str, Any]]:
        cutoff = datetime.now() - timedelta(hours=max(1, since_hours))
        async with self._lock:
            result = []
            for entry in self._entries:
                try:
                    if datetime.fromisoformat(str(entry.get("ts"))) >= cutoff:
                        result.append(dict(entry))
                except (TypeError, ValueError):
                    continue
            return result

    async def contains_article(self, article_id: str) -> bool:
        """Check a persistent article ID so on-demand backfills are idempotent."""
        normalized_id = str(article_id).strip()
        if not normalized_id:
            return False
        async with self._lock:
            return any(entry.get("article_id") == normalized_id for entry in self._entries)


def aggregate_sentiment_by_code(
    entries: list[dict[str, Any]],
    watchlist: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """관심종목 코드별 뉴스 건수·평균 감성을 집계한다."""
    stats: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sentiment = entry.get("sentiment")
        codes = entry.get("codes") or []
        for code in codes:
            code = str(code)
            if code not in watchlist:
                continue
            bucket = stats.setdefault(
                code, {"count": 0, "sentiment_sum": 0.0, "scored": 0, "titles": []}
            )
            bucket["count"] += 1
            if len(bucket["titles"]) < 3:
                bucket["titles"].append(str(entry.get("title") or ""))
            if isinstance(sentiment, (int, float)):
                bucket["sentiment_sum"] += float(sentiment)
                bucket["scored"] += 1
    for bucket in stats.values():
        bucket["avg_sentiment"] = (
            bucket["sentiment_sum"] / bucket["scored"] if bucket["scored"] else None
        )
    return stats


def aggregate_market_sentiment(
    entries: list[dict[str, Any]],
    since_hours: int,
) -> dict[str, dict[str, Any]]:
    """Aggregate scored news into market-level daily trend data.

    An article is counted once for its assigned market, regardless of how many
    watchlist symbols it mentions.  This makes the market view a news-mood
    indicator rather than a watchlist-size indicator.
    """
    cutoff = datetime.now() - timedelta(hours=max(1, since_hours))
    markets: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sentiment = entry.get("sentiment")
        if not isinstance(sentiment, (int, float)):
            continue
        try:
            ts = datetime.fromisoformat(str(entry.get("ts")))
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        market = str(entry.get("market") or "OTHER").strip().upper()
        bucket = markets.setdefault(market, {"sum": 0.0, "count": 0, "daily": {}})
        value = max(-1.0, min(1.0, float(sentiment)))
        bucket["sum"] += value
        bucket["count"] += 1
        day = ts.date().isoformat()
        daily = bucket["daily"].setdefault(day, {"sum": 0.0, "count": 0})
        daily["sum"] += value
        daily["count"] += 1

    for bucket in markets.values():
        bucket["avg_sentiment"] = bucket["sum"] / bucket["count"]
        bucket["daily"] = [
            {"date": day, "avg_sentiment": point["sum"] / point["count"], "count": point["count"]}
            for day, point in sorted(bucket["daily"].items())
        ]
    return markets


def market_history_gaps(
    markets: dict[str, dict[str, Any]],
    required_markets: set[str],
    minimum_articles: int,
    minimum_days: int,
) -> dict[str, str]:
    """Return per-market readiness gaps for a chart-worthy sentiment series."""
    gaps: dict[str, str] = {}
    for market in sorted(required_markets):
        stats = markets.get(market)
        if stats is None:
            gaps[market] = "no scored articles"
            continue
        if stats["count"] < minimum_articles:
            gaps[market] = f"{stats['count']}/{minimum_articles} scored articles"
            continue
        day_count = len(stats["daily"])
        if day_count < minimum_days:
            gaps[market] = f"{day_count}/{minimum_days} calendar days"
    return gaps
