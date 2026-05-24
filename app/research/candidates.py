import logging
import re
from typing import Any, Dict

from stock_db import StockDatabase

logger = logging.getLogger(__name__)

_RESEARCH_KEYWORD_MAP: dict[str, list[str]] = {
    "ai": ["人工智能", "智能", "大模型", "算力"],
    "인공지능": ["人工智能", "智能", "大模型"],
    "llm": ["大模型", "人工智能"],
    "반도체": ["半导体", "芯片", "集成电路", "晶圆"],
    "칩": ["芯片", "半导体"],
    "전기차": ["新能源", "电动", "汽车"],
    "ev": ["新能源", "电动"],
    "배터리": ["电池", "储能", "锂"],
    "태양광": ["光伏", "太阳能"],
    "신재생": ["光伏", "风电", "新能源"],
    "풍력": ["风电", "风能"],
    "로봇": ["机器人", "自动化"],
    "클라우드": ["云计算", "云服务"],
    "5g": ["通信", "5G"],
    "통신": ["通信", "电信"],
    "바이오": ["生物", "基因"],
    "제약": ["医药", "药业", "制药"],
    "헬스케어": ["医疗", "医药", "健康"],
    "소비재": ["消费", "零售"],
    "부동산": ["地产", "房地产"],
    "금융": ["金融", "银行", "证券"],
    "은행": ["银行"],
    "증권": ["证券"],
    "에너지": ["能源", "电力"],
    "원유": ["石油", "能源"],
    "방산": ["军工", "航空"],
    "인터넷": ["互联网", "网络"],
    "플랫폼": ["互联网", "平台"],
    "게임": ["游戏"],
    "장비": ["设备", "仪器"],
}


def _name_is_matchable(name: str) -> bool:
    name = name.strip()
    if len(name) >= 3:
        return True
    return len(name) >= 4 and name.isascii()


def _entry_display_name(entry: dict[str, str]) -> str:
    return str(entry.get("display_name") or entry.get("ko_name") or "").strip()


def _entry_search_text(entry: dict[str, str]) -> str:
    return " ".join(
        value
        for value in (
            str(entry.get("cn_name") or "").strip(),
            _entry_display_name(entry),
        )
        if value
    )


def _extract_research_cn_patterns(market_view: str) -> list[str]:
    research_lower = market_view.lower()
    patterns: list[str] = []
    for keyword, cn_list in _RESEARCH_KEYWORD_MAP.items():
        if keyword in research_lower:
            patterns.extend(cn_list)
    return list(dict.fromkeys(patterns))


def _news_evidence(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(item.get("title") or ""),
        "source": str(item.get("source") or ""),
        "published_at": str(item.get("published_at") or ""),
        "url": str(item.get("url") or ""),
    }


def _resolve_stock_db_code(raw_code: Any) -> str | None:
    code = str(raw_code or "").strip()
    if not code:
        return None
    if code.isdigit():
        return code.zfill(5) if len(code) <= 5 else code.zfill(6)
    return code


def _extract_theme_patterns(theme_candidate: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(theme_candidate.get(field) or "")
        for field in ("keyword", "theme", "reason")
    )
    text_lower = text.lower()
    patterns: list[str] = []

    for keyword, cn_list in _RESEARCH_KEYWORD_MAP.items():
        if keyword in text_lower or any(cn in text for cn in cn_list):
            patterns.extend(cn_list)

    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text):
        if len(token) >= 2 and re.search(r"[\u4e00-\u9fff]", token):
            patterns.append(token)

    return list(dict.fromkeys(patterns))


def _theme_relation_fields(theme_candidate: dict[str, Any]) -> tuple[str, str]:
    keyword = str(theme_candidate.get("keyword") or "").strip()
    theme = str(theme_candidate.get("theme") or "").strip()
    reason = str(theme_candidate.get("reason") or "").strip()
    relation_keyword = keyword or theme
    relation_reason = reason or theme or keyword
    return relation_keyword, relation_reason


def _add_theme_candidate(
    candidates: dict[str, dict[str, Any]],
    entry: dict[str, str],
    watchlist: Dict[str, str],
    evidence: dict[str, str],
    relation_keyword: str,
    relation_reason: str,
) -> bool:
    code = str(entry.get("code") or "")
    if not code:
        return False

    if code in candidates:
        candidate = candidates[code]
        matched_news = candidate.setdefault("matched_news", [])
        if not any(news.get("title") == evidence.get("title") for news in matched_news):
            matched_news.append(evidence)
        candidate.setdefault("relation_keyword", relation_keyword)
        candidate.setdefault("relation_reason", relation_reason)
        return False

    candidates[code] = {
        "code": code,
        "name": _entry_display_name(entry),
        "market": str(entry.get("market") or ""),
        "in_watchlist": code in watchlist,
        "matched_news": [evidence],
        "relation_keyword": relation_keyword,
        "relation_reason": relation_reason,
    }
    return True


def build_research_candidate_universe(
    stock_db: StockDatabase,
    watchlist: Dict[str, str],
    news_items: list[dict[str, Any]],
    market_view: str = "",
    max_candidates: int = 30,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    haystacks = [
        f"{item.get('title', '')}\n{item.get('content', '')}"
        for item in news_items
    ]
    stock_entries = stock_db.get_candidate_universe()
    entries_by_code = {
        str(entry.get("code") or ""): entry
        for entry in stock_entries
        if str(entry.get("code") or "")
    }

    for code, name in watchlist.items():
        candidates[code] = {
            "code": code,
            "name": name,
            "market": "",
            "in_watchlist": True,
            "matched_news": [],
        }

    cn_patterns = _extract_research_cn_patterns(market_view) if market_view else []
    if cn_patterns:
        research_added = 0
        for entry in stock_entries:
            code = str(entry.get("code") or "")
            name = _entry_display_name(entry)
            search_text = _entry_search_text(entry)
            if not code or not name or code in candidates:
                continue
            if any(pat in search_text for pat in cn_patterns):
                candidates[code] = {
                    "code": code,
                    "name": name,
                    "market": entry.get("market", ""),
                    "in_watchlist": False,
                    "matched_news": [],
                }
                research_added += 1
        logger.info("[RESEARCH] 키워드 후보 %d개 추가 (패턴: %s)", research_added, cn_patterns[:5])

    mentioned_added = 0
    for item in news_items:
        mentioned_stocks = item.get("mentioned_stocks", [])
        if not isinstance(mentioned_stocks, list):
            continue
        evidence = _news_evidence(item)
        for raw_code in mentioned_stocks:
            resolved_code = _resolve_stock_db_code(raw_code)
            if not resolved_code or resolved_code in candidates:
                continue
            entry = entries_by_code.get(resolved_code, {})
            candidates[resolved_code] = {
                "code": resolved_code,
                "name": _entry_display_name(entry),
                "market": str(entry.get("market") or ""),
                "in_watchlist": resolved_code in watchlist,
                "matched_news": [evidence],
            }
            mentioned_added += 1
    if mentioned_added:
        logger.info("[RESEARCH] 직접 언급 후보 %d개 추가", mentioned_added)

    for entry in stock_entries:
        code = str(entry.get("code") or "")
        name = _entry_display_name(entry)
        search_text = _entry_search_text(entry)
        if not code or not name or not _name_is_matchable(name):
            continue

        matched_news = []
        for item, haystack in zip(news_items, haystacks):
            if name in haystack or (
                search_text and any(part in haystack for part in search_text.split())
            ):
                matched_news.append(
                    {
                        "title": item.get("title", ""),
                        "source": item.get("source", ""),
                        "published_at": item.get("published_at", ""),
                        "url": item.get("url", ""),
                    }
                )
                item.setdefault("matched_candidates", [])
                item["matched_candidates"].append(
                    {
                        "code": code,
                        "name": name,
                        "market": entry.get("market", ""),
                    }
                )

        if not matched_news:
            continue

        candidates[code] = {
            "code": code,
            "name": name,
            "market": entry.get("market", ""),
            "in_watchlist": code in watchlist,
            "matched_news": matched_news[:3],
        }

    theme_added = 0
    for item in news_items:
        theme_candidates = item.get("theme_candidates", [])
        if not isinstance(theme_candidates, list):
            continue

        evidence = _news_evidence(item)
        for theme_candidate in theme_candidates:
            if not isinstance(theme_candidate, dict):
                continue
            relation_keyword, relation_reason = _theme_relation_fields(theme_candidate)

            codes = theme_candidate.get("codes", [])
            if isinstance(codes, list):
                for raw_code in codes:
                    resolved_code = _resolve_stock_db_code(raw_code)
                    if not resolved_code:
                        continue
                    entry = entries_by_code.get(
                        resolved_code,
                        {"code": resolved_code, "display_name": "", "market": ""},
                    )
                    if _add_theme_candidate(
                        candidates,
                        entry,
                        watchlist,
                        evidence,
                        relation_keyword,
                        relation_reason,
                    ):
                        theme_added += 1

            patterns = _extract_theme_patterns(theme_candidate)
            if not patterns:
                continue
            for entry in stock_entries:
                code = str(entry.get("code") or "")
                name = _entry_display_name(entry)
                search_text = _entry_search_text(entry)
                if not code or not name or code in candidates:
                    continue
                if any(pattern in search_text for pattern in patterns):
                    if _add_theme_candidate(
                        candidates,
                        entry,
                        watchlist,
                        evidence,
                        relation_keyword,
                        relation_reason,
                    ):
                        theme_added += 1

    if theme_added:
        logger.info("[RESEARCH] 테마 후보 %d개 추가", theme_added)

    return list(candidates.values())[:max_candidates]
