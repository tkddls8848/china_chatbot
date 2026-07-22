"""리서치 후보 발굴이 미국·한국 universe 종목을 다루는지 검증."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from research.candidates import build_research_candidate_universe
from stocks import StockDatabase


def _db(tmp_path) -> StockDatabase:
    cache = tmp_path / "stock_db.json"
    cache.write_text(
        json.dumps(
            {
                "300750": {
                    "display_name": "CATL",
                    "cn_name": "宁德时代",
                    "ko_name": "닝더스다이",
                    "market": "SZ",
                },
                "US:NASDAQ:AAPL": {
                    "display_name": "Apple Inc. - Common Stock",
                    "cn_name": "",
                    "ko_name": "Apple Inc. - Common Stock",
                    "market": "US",
                },
                "US:NASDAQ:ONSC": {
                    "display_name": "On Semiconductor Corporation - Common Stock",
                    "cn_name": "",
                    "ko_name": "",
                    "market": "US",
                },
                "KR:KOSPI:005930": {
                    "display_name": "삼성전자",
                    "cn_name": "",
                    "ko_name": "삼성전자",
                    "market": "KR",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db = StockDatabase(cache_file=cache)
    db.load()
    return db


def test_keyword_patterns_match_us_and_kr_entries(tmp_path):
    candidates = build_research_candidate_universe(
        _db(tmp_path),
        watchlist={},
        news_items=[],
        market_view="반도체 업황 회복",
        keyword_candidates=True,
    )
    codes = {c["code"] for c in candidates}
    assert "US:NASDAQ:ONSC" in codes  # display_name의 Semiconductor 매칭
    assert "KR:KOSPI:005930" not in codes  # 이름에 반도체가 없으면 미매칭


def test_keyword_candidates_are_off_by_default(tmp_path):
    # 이름 문자열이 겹칠 뿐인 후보는 근거 있는 후보를 상한 밖으로 밀어낸다.
    candidates = build_research_candidate_universe(
        _db(tmp_path),
        watchlist={},
        news_items=[],
        market_view="반도체 업황 회복",
    )
    assert candidates == []


def test_keyword_candidates_respect_limit_and_rotate_markets(tmp_path):
    entries = {
        f"60{i:04d}": {"display_name": f"반도체기업{i}", "cn_name": f"半导体公司{i}", "market": "SH"}
        for i in range(20)
    }
    entries["US:NASDAQ:ONSC"] = {
        "display_name": "On Semiconductor Corporation",
        "cn_name": "",
        "market": "US",
    }
    cache = tmp_path / "stock_db.json"
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    db = StockDatabase(cache_file=cache)
    db.load()

    candidates = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[],
        market_view="반도체",
        keyword_candidates=True,
        keyword_limit=4,
    )

    assert len(candidates) == 4
    # A주가 상한을 독식하지 않고 미국 종목도 들어온다.
    assert "US:NASDAQ:ONSC" in {c["code"] for c in candidates}


def test_english_stopword_tokens_do_not_match_news(tmp_path):
    # "Common Stock" 같은 일반 단어로는 뉴스와 매칭되지 않아야 한다.
    candidates = build_research_candidate_universe(
        _db(tmp_path),
        watchlist={},
        news_items=[{"title": "Common stock market talk", "content": "shares up"}],
    )
    assert not any(c["code"].startswith("US:") for c in candidates)


def _db_from(entries: dict, tmp_path) -> StockDatabase:
    cache = tmp_path / "stock_db.json"
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    db = StockDatabase(cache_file=cache)
    db.load()
    return db


def test_tokens_shared_by_many_listings_do_not_match_news(tmp_path):
    # "Big Tech earnings" 한 줄이 이름에 TECH가 든 종목을 전부 끌어오면 안 된다.
    entries = {
        f"0{i:04d}": {"display_name": f"NEXION TECH {i}", "cn_name": "", "market": "HK"}
        for i in range(20)
    }
    db = _db_from(entries, tmp_path)

    candidates = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[{"title": "Stocks slide with Big Tech earnings ahead", "content": ""}],
        max_candidates=50,
        name_token_max_frequency=15,
    )

    assert candidates == []


def test_multi_word_english_names_need_two_matching_tokens(tmp_path):
    # 종목 DB에서는 드물지만 영어 기사에서는 흔한 단어(daily)가 하나 걸렸다고
    # 후보가 되면 안 된다. 이름이 한 단어인 종목은 하나만 걸려도 인정한다.
    db = _db_from(
        {
            "US:NASDAQ:DJCO": {
                "display_name": "Daily Journal Corp.",
                "cn_name": "",
                "market": "US",
            },
            "US:NASDAQ:GOOGL": {
                "display_name": "Alphabet Inc. - Class A Common Stock",
                "cn_name": "",
                "market": "US",
            },
        },
        tmp_path,
    )

    weak = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[{"title": "Wall Street daily wrap: Alphabet slides", "content": ""}],
        max_candidates=50,
    )
    assert {c["code"] for c in weak} == {"US:NASDAQ:GOOGL"}

    strong = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[{"title": "Daily Journal reports annual results", "content": ""}],
        max_candidates=50,
    )
    assert {c["code"] for c in strong} == {"US:NASDAQ:DJCO"}


def test_english_name_token_matches_news(tmp_path):
    candidates = build_research_candidate_universe(
        _db(tmp_path),
        watchlist={},
        news_items=[{"title": "Apple unveils new AI features", "content": ""}],
    )
    apple = next(c for c in candidates if c["code"] == "US:NASDAQ:AAPL")
    assert apple["matched_news"]


def test_mentioned_stocks_resolve_universe_alias(tmp_path):
    candidates = build_research_candidate_universe(
        _db(tmp_path),
        watchlist={},
        news_items=[
            {
                "title": "빅테크·반도체 동반 강세",
                "content": "",
                "mentioned_stocks": ["AAPL", "005930"],
            }
        ],
    )
    codes = {c["code"] for c in candidates}
    assert "US:NASDAQ:AAPL" in codes
    assert "KR:KOSPI:005930" in codes


def test_cap_keeps_evidenced_and_multimarket_candidates(tmp_path):
    # A주 키워드 매칭이 상한을 독식해도 뉴스 언급 후보(미국·한국)는 살아남아야 한다.
    entries = {
        f"60{i:04d}": {
            "display_name": f"지능기업{i}",
            "cn_name": f"智能公司{i}",
            "ko_name": "",
            "market": "SH",
        }
        for i in range(40)
    }
    entries["US:NASDAQ:AAPL"] = {
        "display_name": "Apple Inc. - Common Stock",
        "cn_name": "",
        "ko_name": "",
        "market": "US",
    }
    entries["KR:KOSPI:005930"] = {
        "display_name": "삼성전자",
        "cn_name": "",
        "ko_name": "삼성전자",
        "market": "KR",
    }
    cache = tmp_path / "stock_db.json"
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    db = StockDatabase(cache_file=cache)
    db.load()

    candidates = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[
            {
                "title": "AI 훈풍",
                "content": "",
                "mentioned_stocks": ["AAPL", "005930"],
            }
        ],
        market_view="ai",
        max_candidates=30,
    )
    codes = {c["code"] for c in candidates}
    assert len(candidates) <= 30
    assert "US:NASDAQ:AAPL" in codes
    assert "KR:KOSPI:005930" in codes


def test_theme_codes_are_kept_but_name_matches_are_capped(tmp_path):
    entries = {
        f"60{i:04d}": {"display_name": f"지능기업{i}", "cn_name": f"人工智能公司{i}", "market": "SH"}
        for i in range(30)
    }
    entries["US:NASDAQ:AAPL"] = {"display_name": "Apple Inc.", "cn_name": "", "market": "US"}
    cache = tmp_path / "stock_db.json"
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    db = StockDatabase(cache_file=cache)
    db.load()

    candidates = build_research_candidate_universe(
        db,
        watchlist={},
        news_items=[
            {
                "title": "AI 훈풍",
                "content": "",
                "theme_candidates": [
                    {
                        "keyword": "人工智能",
                        "theme": "AI",
                        "reason": "정책 지원",
                        "codes": ["AAPL"],  # LLM이 코드를 명시한 후보는 제한하지 않는다
                    }
                ],
            }
        ],
        max_candidates=50,
        theme_pattern_limit=3,
    )

    codes = {c["code"] for c in candidates}
    assert "US:NASDAQ:AAPL" in codes
    assert len(codes - {"US:NASDAQ:AAPL"}) == 3  # 이름 매칭 후보는 상한까지만


def test_stock_db_resolve_code_aliases(tmp_path):
    db = _db(tmp_path)
    assert db.resolve_code("300750") == "300750"
    assert db.resolve_code("aapl") == "US:NASDAQ:AAPL"
    assert db.resolve_code("005930") == "KR:KOSPI:005930"
    assert db.resolve_code("US:NASDAQ:AAPL") == "US:NASDAQ:AAPL"
    assert db.resolve_code("999999") is None


def test_normalize_code_preserves_universe_keys():
    from research.handlers import _normalize_code

    assert _normalize_code("US:NASDAQ:AAPL") == "US:NASDAQ:AAPL"
    assert _normalize_code("aapl") == "AAPL"
    assert _normalize_code("300750") == "300750"
    assert _normalize_code("700") == "00700"
