import logging
import re
from collections import Counter
from typing import Any, Dict

from core.config import (
    RESEARCH_KEYWORD_CANDIDATE_LIMIT,
    RESEARCH_KEYWORD_CANDIDATES_ENABLED,
    RESEARCH_NAME_TOKEN_MAX_FREQUENCY,
    RESEARCH_THEME_PATTERN_CANDIDATE_LIMIT,
)
from stocks import StockDatabase

logger = logging.getLogger(__name__)

# 리서치 주제 키워드 → 종목명 매칭 패턴(중국어·한국어·영어 혼합).
# 중국어/한국어 패턴은 부분 문자열, 영어 패턴은 단어 경계 기준으로 매칭한다.
_RESEARCH_KEYWORD_MAP: dict[str, list[str]] = {
    "ai": ["人工智能", "智能", "大模型", "算力", "인공지능", "AI", "artificial intelligence"],
    "인공지능": ["人工智能", "智能", "大模型", "인공지능", "AI"],
    "llm": ["大模型", "人工智能", "인공지능", "AI"],
    "반도체": ["半导体", "芯片", "集成电路", "晶圆", "반도체", "semiconductor"],
    "칩": ["芯片", "半导体", "반도체", "semiconductor"],
    "전기차": ["新能源", "电动", "汽车", "전기차", "모빌리티", "electric vehicle", "motors"],
    "ev": ["新能源", "电动", "전기차", "EV", "electric vehicle"],
    "배터리": ["电池", "储能", "锂", "배터리", "이차전지", "에너지솔루션", "battery", "lithium"],
    "태양광": ["光伏", "太阳能", "태양광", "solar"],
    "신재생": ["光伏", "风电", "新能源", "신재생", "solar", "renewable"],
    "풍력": ["风电", "风能", "풍력", "wind"],
    "로봇": ["机器人", "自动化", "로봇", "로보", "robot", "automation"],
    "클라우드": ["云计算", "云服务", "클라우드", "cloud"],
    "5g": ["通信", "5G", "통신", "telecom"],
    "통신": ["通信", "电信", "통신", "텔레콤", "telecom", "communications"],
    "바이오": ["生物", "基因", "바이오", "bio", "genomics"],
    "제약": ["医药", "药业", "制药", "제약", "파마", "pharma"],
    "헬스케어": ["医疗", "医药", "健康", "헬스", "메디", "health", "medical"],
    "소비재": ["消费", "零售", "리테일", "유통", "consumer", "retail"],
    "부동산": ["地产", "房地产", "부동산", "realty", "properties"],
    "금융": ["金融", "银行", "证券", "금융", "은행", "증권", "financial", "bank"],
    "은행": ["银行", "은행", "bank"],
    "증권": ["证券", "증권", "securities"],
    "에너지": ["能源", "电力", "에너지", "전력", "energy", "power"],
    "원유": ["石油", "能源", "석유", "오일", "oil", "petroleum"],
    "방산": ["军工", "航空", "방산", "우주항공", "defense", "aerospace"],
    "인터넷": ["互联网", "网络", "인터넷", "internet"],
    "플랫폼": ["互联网", "平台", "플랫폼", "platforms"],
    "게임": ["游戏", "게임", "games", "gaming"],
    "장비": ["设备", "仪器", "장비", "equipment", "instruments"],
}

# 영문 종목명 토큰 매칭에서 제외할 일반 단어(법인 형태·증권 유형 등).
_NAME_TOKEN_STOPWORDS = {
    "inc", "corp", "corporation", "incorporated", "company", "ltd", "limited",
    "plc", "group", "holdings", "holding", "class", "common", "stock", "stocks",
    "share", "shares", "ordinary", "preferred", "series", "trust", "fund",
    "depositary", "depository", "adr", "ads", "notes", "warrant", "warrants",
    "unit", "units", "right", "rights", "the", "and", "of", "new", "each",
    "per", "value", "beneficial", "interest", "interests", "capital",
    "international", "acquisition", "representing",
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


def _extract_research_patterns(market_view: str) -> list[str]:
    """리서치 주제에서 종목명 매칭 패턴(중·한·영)을 뽑는다."""
    research_lower = market_view.lower()
    patterns: list[str] = []
    for keyword, pattern_list in _RESEARCH_KEYWORD_MAP.items():
        if keyword in research_lower:
            patterns.extend(pattern_list)
    return list(dict.fromkeys(patterns))


def _extract_research_cn_patterns(market_view: str) -> list[str]:
    """중국어 패턴만(问财 쿼리 등 중국 전용 소스용)."""
    return [
        pattern
        for pattern in _extract_research_patterns(market_view)
        if re.search(r"[一-鿿]", pattern)
    ]


def _build_pattern_matcher(patterns: list[str], whole_word: bool = False):
    """패턴 목록 → 텍스트 매칭 함수.

    기본(종목명 매칭용): 중국어·한글은 부분 문자열, 영어는 단어 경계 기준
    (2자 이하는 완전 일치, 3자 이상은 접두 일치).
    whole_word=True(뉴스 본문 매칭용): 영어는 완전 단어 일치, 한글은 앞글자
    경계를 요구해 "이닉스"가 "하이닉스"에 걸리는 오탐을 막는다(조사는 허용).
    """
    substring: list[str] = []
    regex_parts: list[str] = []
    for pattern in dict.fromkeys(p for p in patterns if p):
        escaped = re.escape(pattern)
        if pattern.isascii():
            if whole_word or len(pattern) <= 2:
                regex_parts.append(rf"\b{escaped}\b")
            else:
                regex_parts.append(rf"\b{escaped}")
        elif whole_word and re.search(r"[가-힣]", pattern):
            regex_parts.append(rf"(?<![가-힣]){escaped}")
        else:
            substring.append(pattern)
    regex = re.compile("|".join(regex_parts), re.IGNORECASE) if regex_parts else None

    def matches(text: str) -> bool:
        if any(p in text for p in substring):
            return True
        return regex is not None and regex.search(text) is not None

    return matches


def _english_name_tokens(value: str) -> list[str]:
    """영문 종목명 → 매칭 후보 토큰(4자 이상, 법인 형태 등 일반 단어 제외)."""
    return [
        token
        for token in re.findall(r"[A-Za-z]{4,}", value)
        if token.lower() not in _NAME_TOKEN_STOPWORDS
    ]


def _build_name_token_frequency(stock_entries: list[dict[str, str]]) -> Counter:
    """토큰별로 그 토큰을 이름에 가진 종목 수를 센다.

    'TECH'·'ENERGY'처럼 수십~수백 종목이 공유하는 토큰은 뉴스에 한 번 나오면
    무관한 종목을 무더기로 끌어온다("Big Tech earnings" → 이름에 TECH가 든
    모든 종목). 어느 단어가 흔한지는 시장마다 다르므로 목록을 손으로 관리하지
    않고 종목 DB에서 직접 센다.
    """
    frequency: Counter = Counter()
    for entry in stock_entries:
        tokens: set[str] = set()
        for value in (
            str(entry.get("cn_name") or "").strip(),
            _entry_display_name(entry),
        ):
            if value and value.isascii():
                tokens.update(token.lower() for token in _english_name_tokens(value))
        frequency.update(tokens)
    return frequency


def _entry_match_terms(
    entry: dict[str, str],
    token_frequency: Counter | None = None,
    max_token_frequency: int = RESEARCH_NAME_TOKEN_MAX_FREQUENCY,
) -> list[str]:
    """뉴스 본문 매칭용 종목명 용어.

    영문명은 일반 단어를 제외한 토큰으로 나누고, 여러 종목이 공유하는 흔한
    토큰은 버린다. 남는 토큰이 없으면 이 종목은 이름 매칭 대상에서 빠진다.
    중국어·한국어 이름은 통째로 쓰므로 이 필터를 거치지 않는다.
    """
    terms: list[str] = []
    for value in (
        str(entry.get("cn_name") or "").strip(),
        _entry_display_name(entry),
    ):
        if not value:
            continue
        if value.isascii():
            for token in _english_name_tokens(value):
                if (
                    token_frequency is not None
                    and token_frequency.get(token.lower(), 0) > max_token_frequency
                ):
                    continue
                terms.append(token)
        else:
            terms.append(value)
    return list(dict.fromkeys(terms))


def _build_name_matcher(match_terms: list[str]):
    """뉴스 본문에서 이 종목을 가리키는지 판정한다.

    영문명은 **서로 다른 토큰 2개 이상**이 같은 기사에 나와야 한다. 종목 DB에서는
    드물지만 영어 기사에서는 흔한 단어(Daily, Home, Better...)가 한 개만 걸려도
    무관한 종목이 후보로 올라오기 때문이다("Daily Journal" ← 기사 속 daily).
    이름이 한 단어면 그 자체가 고유하므로 1개로 충분하다.
    중국어·한국어 이름은 통째로 쓰며 기존 경계 규칙을 그대로 따른다.
    """
    cjk_terms = [term for term in match_terms if not term.isascii()]
    tokens = [term for term in match_terms if term.isascii()]
    cjk_matcher = _build_pattern_matcher(cjk_terms, whole_word=True) if cjk_terms else None
    token_patterns = [
        re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE) for token in tokens
    ]
    required = min(2, len(token_patterns))

    def matches(text: str) -> bool:
        if cjk_matcher is not None and cjk_matcher(text):
            return True
        hits = 0
        for pattern in token_patterns:
            if pattern.search(text):
                hits += 1
                if hits >= required:
                    return True
        return False

    return matches


def _rotate_by_market(by_market: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """시장별 후보 목록을 번갈아 하나씩 뽑아 이어 붙인다(입력은 보존)."""
    rotated: list[dict[str, Any]] = []
    queues = [list(queue) for queue in by_market.values() if queue]
    while queues:
        remaining = []
        for queue in queues:
            rotated.append(queue.pop(0))
            if queue:
                remaining.append(queue)
        queues = remaining
    return rotated


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
    return code.upper()  # 미국 티커·universe 키(US:NASDAQ:AAPL)는 대문자로 정규화


def _extract_theme_patterns(theme_candidate: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(theme_candidate.get(field) or "")
        for field in ("keyword", "theme", "reason")
    )
    text_lower = text.lower()
    patterns: list[str] = []

    for keyword, pattern_list in _RESEARCH_KEYWORD_MAP.items():
        if keyword in text_lower or any(p in text for p in pattern_list if not p.isascii()):
            patterns.extend(pattern_list)

    for token in re.findall(r"[\u4e00-\u9fff\uac00-\ud7a3A-Za-z0-9]+", text):
        if len(token) >= 2 and re.search(r"[\u4e00-\u9fff\uac00-\ud7a3]", token):
            patterns.append(token)  # \uc911\uad6d\uc5b4\u00b7\ud55c\uad6d\uc5b4 \ud1a0\ud070
        elif (
            token.isascii()
            and token.isalpha()
            and len(token) >= 4
            and token.lower() not in _NAME_TOKEN_STOPWORDS
        ):
            patterns.append(token)  # \uc601\uc5b4 \ud1a0\ud070(\uc77c\ubc18 \ub2e8\uc5b4 \uc81c\uc678)

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
    keyword_candidates: bool = RESEARCH_KEYWORD_CANDIDATES_ENABLED,
    keyword_limit: int = RESEARCH_KEYWORD_CANDIDATE_LIMIT,
    theme_pattern_limit: int = RESEARCH_THEME_PATTERN_CANDIDATE_LIMIT,
    name_token_max_frequency: int = RESEARCH_NAME_TOKEN_MAX_FREQUENCY,
) -> list[dict[str, Any]]:
    """후보 universe를 근거 강도 순으로 만든다.

    근거 등급: 관심종목 > LLM이 코드를 명시한 후보(mentioned_stocks·테마 codes)
    > 뉴스 본문 종목명 매칭 > 이름 문자열이 키워드와 겹치는 후보. 마지막 등급은
    근거가 약하면서 수백 개씩 잡히므로 기본적으로 만들지 않거나 상한을 둔다.
    """
    candidates: dict[str, dict[str, Any]] = {}
    haystacks = [
        f"{item.get('title', '')}\n{item.get('content', '')}"
        for item in news_items
    ]
    all_text = "\n".join(haystacks)
    all_text_lower = all_text.lower()
    stock_entries = stock_db.get_candidate_universe()
    entries_by_code = {
        str(entry.get("code") or ""): entry
        for entry in stock_entries
        if str(entry.get("code") or "")
    }
    # 미국·한국 universe 키(US:NASDAQ:AAPL)는 접미 코드(AAPL)로도 찾을 수 있게
    # 별칭을 추가한다. 중화권 코드와 겹치면 원본이 우선한다.
    for entry in stock_entries:
        code = str(entry.get("code") or "")
        if ":" in code:
            entries_by_code.setdefault(code.rsplit(":", 1)[-1], entry)

    for code, name in watchlist.items():
        candidates[code] = {
            "code": code,
            "name": name,
            "market": "",
            "in_watchlist": True,
            "matched_news": [],
        }

    view_patterns = (
        _extract_research_patterns(market_view)
        if market_view and keyword_candidates and keyword_limit > 0
        else []
    )
    if view_patterns:
        matcher = _build_pattern_matcher(view_patterns)
        # 시장별로 번갈아 담아, 상한이 한 시장(주로 A주)에 쏠리지 않게 한다.
        by_market: dict[str, list[dict[str, Any]]] = {}
        for entry in stock_entries:
            code = str(entry.get("code") or "")
            name = _entry_display_name(entry)
            if not code or not name or code in candidates:
                continue
            if matcher(_entry_search_text(entry)):
                by_market.setdefault(str(entry.get("market") or ""), []).append(
                    {
                        "code": code,
                        "name": name,
                        "market": entry.get("market", ""),
                        "in_watchlist": False,
                        "matched_news": [],
                    }
                )
        research_added = 0
        for candidate in _rotate_by_market(by_market)[:keyword_limit]:
            candidates[candidate["code"]] = candidate
            research_added += 1
        logger.info("[RESEARCH] 키워드 후보 %d개 추가 (패턴: %s)", research_added, view_patterns[:5])

    mentioned_added = 0
    for item in news_items:
        mentioned_stocks = item.get("mentioned_stocks", [])
        if not isinstance(mentioned_stocks, list):
            continue
        evidence = _news_evidence(item)
        for raw_code in mentioned_stocks:
            resolved_code = _resolve_stock_db_code(raw_code)
            if not resolved_code:
                continue
            entry = entries_by_code.get(resolved_code, {})
            # 별칭(AAPL 등)으로 찾았으면 universe 키를 대표 코드로 쓴다.
            canonical = str(entry.get("code") or "") or resolved_code
            if canonical in candidates:
                continue
            candidates[canonical] = {
                "code": canonical,
                "name": _entry_display_name(entry),
                "market": str(entry.get("market") or ""),
                "in_watchlist": canonical in watchlist,
                "matched_news": [evidence],
            }
            mentioned_added += 1
    if mentioned_added:
        logger.info("[RESEARCH] 직접 언급 후보 %d개 추가", mentioned_added)

    token_frequency = _build_name_token_frequency(stock_entries)
    for entry in stock_entries:
        code = str(entry.get("code") or "")
        name = _entry_display_name(entry)
        if not code or not name or not _name_is_matchable(name):
            continue
        match_terms = _entry_match_terms(entry, token_frequency, name_token_max_frequency)
        if not match_terms:
            continue
        # 값싼 부분 문자열 사전 필터: 전체 뉴스에 안 나오는 이름은 정규식 생략
        if not any(
            (term.lower() in all_text_lower) if term.isascii() else (term in all_text)
            for term in match_terms
        ):
            continue
        name_matcher = _build_name_matcher(match_terms)

        matched_news = []
        for item, haystack in zip(news_items, haystacks):
            if name_matcher(haystack):
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
    theme_pattern_added = 0
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

            # 코드가 아니라 이름 문자열로만 걸린 테마 후보는 근거가 약하므로
            # 전체 뉴스를 통틀어 theme_pattern_limit개까지만 받는다.
            if theme_pattern_added >= theme_pattern_limit:
                continue
            patterns = _extract_theme_patterns(theme_candidate)
            if not patterns:
                continue
            theme_matcher = _build_pattern_matcher(patterns)
            for entry in stock_entries:
                if theme_pattern_added >= theme_pattern_limit:
                    break
                code = str(entry.get("code") or "")
                name = _entry_display_name(entry)
                search_text = _entry_search_text(entry)
                if not code or not name or code in candidates:
                    continue
                if theme_matcher(search_text):
                    if _add_theme_candidate(
                        candidates,
                        entry,
                        watchlist,
                        evidence,
                        relation_keyword,
                        relation_reason,
                    ):
                        theme_added += 1
                        theme_pattern_added += 1

    if theme_added:
        logger.info("[RESEARCH] 테마 후보 %d개 추가", theme_added)

    return _prioritize_candidates(list(candidates.values()), max_candidates)


def _prioritize_candidates(
    values: list[dict[str, Any]], max_candidates: int
) -> list[dict[str, Any]]:
    """상한 적용 순서: 관심종목 → 뉴스 근거 보유 → 키워드 전용(시장별 순환).

    키워드 전용 후보를 시장별로 번갈아 뽑아, 특정 시장(예: A주)이
    상한을 독식해 미국·한국 후보가 잘리는 것을 막는다.
    """
    watch = [c for c in values if c.get("in_watchlist")]
    evidenced = [c for c in values if not c.get("in_watchlist") and c.get("matched_news")]
    keyword_only = [
        c for c in values if not c.get("in_watchlist") and not c.get("matched_news")
    ]

    by_market: dict[str, list[dict[str, Any]]] = {}
    for candidate in keyword_only:
        by_market.setdefault(str(candidate.get("market") or ""), []).append(candidate)

    return (watch + evidenced + _rotate_by_market(by_market))[:max_candidates]
