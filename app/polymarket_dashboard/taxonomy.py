"""Polymarket raw tag를 한 개의 대표 분야와 보조 축으로 분류한다."""

from __future__ import annotations

from typing import Any

TAXONOMY_VERSION = "2026-08-30.1"
NAMED_CATEGORY_TARGET = 0.90

CATEGORY_LABELS = {
    "politics": "정치·선거",
    "geopolitics": "지정학·국제",
    "economy_finance": "경제·금융",
    "crypto": "크립토",
    "technology_ai": "기술·AI",
    "business": "기업·비즈니스",
    "sports": "스포츠",
    "culture": "문화·엔터테인먼트",
    "science_health": "과학·건강",
    "weather_climate": "날씨·기후",
    "law_regulation": "법률·규제",
    "other": "기타·미분류",
}

# G0(2026-08-30, 열린 event 22,047건) 상위 raw tag를 모두 검토해 고정했다.
# 세부 리그·코인명은 대표 분야의 명백한 자식이므로 exact allowlist로만 확장한다.
CATEGORY_TAGS: dict[str, set[str]] = {
    "politics": {
        "politics", "elections", "us-presidential-election", "midterms",
        "house-elections", "global-elections", "world-elections", "main-election",
        "international-election-props", "nov-4-elections", "trump", "midtermmov",
    },
    "geopolitics": {
        "geopolitics", "world", "middle-east", "iran", "russia", "ukraine",
        "china", "israel", "war", "foreign-policy",
    },
    "economy_finance": {
        "economy", "finance", "fed", "fed-rates", "macro-indicators", "inflation",
        "interest-rates", "equities", "stocks", "pre-market",
    },
    "crypto": {
        "crypto", "crypto-prices", "bitcoin", "ethereum", "solana", "xrp", "ripple",
        "bnb", "dogecoin", "zcash", "hype", "up-or-down", "5m", "15m", "1h",
    },
    "technology_ai": {"tech", "ai", "big-tech", "technology", "artificial-intelligence"},
    "business": {"business", "companies", "deals", "mergers", "earnings"},
    "sports": {
        "sports", "games", "soccer", "football", "nfl", "mlb", "baseball", "tennis",
        "table-tennis", "cricket", "esports", "counter-strike-2", "league-of-legends",
        "formula-1", "fa-cup", "efl-championship", "mls", "cfb", "epl", "ucl",
        "premier-league", "bundesliga", "bundesliga-2", "la-liga", "la-liga-2",
        "ligue-1", "ligue-2", "serie-b", "national-league", "international-cricket",
        "season-stats", "props", "margin-of-victory", "setka", "setkameua",
        "japan-j-league", "japan-j2-league", "k-league", "brazil-serie-a",
        "saudi-professional-league", "scottish-premiership", "primeira-liga",
    },
    "culture": {"culture", "pop-culture", "awards", "movies", "music", "entertainment"},
    "science_health": {"science", "space", "health", "medicine", "public-health"},
    "weather_climate": {
        "weather", "climate", "temperature", "daily-temperature", "highest-temperature",
        "lowest-temperature",
    },
    "law_regulation": {"legal", "law", "courts", "regulation", "supreme-court"},
}

REGION_TAGS = {
    "us", "usa", "united-states", "brazil", "japan", "korea", "china", "iran",
    "russia", "ukraine", "europe", "middle-east", "mex", "argpn", "sea", "rus",
}
SYSTEM_TAGS = {"hide-from-new", "recurring", "featured", "rewards", "closed"}


def _slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def extract_tags(event: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in event.get("tags") or []:
        if not isinstance(raw, dict):
            continue
        slug = _slug(raw.get("slug") or raw.get("label"))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        result.append({"slug": slug, "label": str(raw.get("label") or slug)})
    return result


def classify(tags: list[dict[str, str]]) -> dict[str, Any]:
    slugs = {tag["slug"] for tag in tags}
    candidates = [key for key, allowed in CATEGORY_TAGS.items() if slugs & allowed]
    if len(candidates) == 1:
        category = candidates[0]
        reason = "tag:" + sorted(slugs & CATEGORY_TAGS[category])[0]
    elif len(candidates) > 1:
        category = "other"
        reason = "ambiguous:" + ",".join(sorted(candidates))
    else:
        category = "other"
        reason = "unmapped"
    return {
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "category_reason": reason,
        "tags": sorted(slugs - REGION_TAGS - SYSTEM_TAGS),
        "regions": sorted(slugs & REGION_TAGS),
        "system_tags": sorted(slugs & SYSTEM_TAGS),
    }
