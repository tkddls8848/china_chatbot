from dataclasses import dataclass, field
from typing import Any


def normalize_stock_code(code: str) -> str:
    value = "".join(ch for ch in str(code).strip() if ch.isdigit())
    if not value:
        return ""
    if len(value) <= 5:
        return value.zfill(5)
    return value.zfill(6)


def is_matchable_stock_name(name: str) -> bool:
    name = name.strip()
    if len(name) >= 3:
        return True
    return len(name) >= 4 and name.isascii()


@dataclass(frozen=True)
class NewsItem:
    id: str
    source: str
    title: str
    content: str
    published_at: str
    url: str = ""
    ticker: str = ""
    name: str = ""
    matched_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "ticker": self.ticker,
            "name": self.name,
            "title": self.title,
            "content": self.content,
            "published_at": self.published_at,
            "url": self.url,
            "matched_candidates": self.matched_candidates,
        }


@dataclass(frozen=True)
class StockRef:
    code: str
    name: str
    market: str = ""
    in_watchlist: bool = False
    matched_news: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "market": self.market,
            "in_watchlist": self.in_watchlist,
            "matched_news": self.matched_news,
        }


@dataclass(frozen=True)
class ViewAction:
    code: str
    name: str
    action: str
    confidence: float
    reason: str
    evidence: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.code,
            "name": self.name,
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ViewAnalysisResult:
    generated_at: str
    summary: str
    actions: list[ViewAction]
    risks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions],
            "risks": self.risks,
        }
