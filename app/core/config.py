"""환경 변수 로딩과 전역 설정 상수.

설정 저장 방침:
  - `.env` = 모든 설정의 유일한 원본. 시작 시 1회, 이 모듈에서만 읽는다.
    다른 모듈은 여기서 상수를 import 하며 `os.environ`에 직접 접근하지 않는다.
  - `data/*.json` = 봇이 수집·축적하는 데이터(관심종목, 전송 이력, 종목 DB 등).
    설정값은 저장하지 않는다. 런타임 변경(/system gpu ...)은 세션 한정이며
    재시작하면 `.env` 값으로 되돌아간다.

import 시 .env 로딩과 로깅 설정이 한 번 수행된다.
"""

import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# pandas 3.0부터 future.infer_string 기본값이 True라 문자열이 pyarrow(RE2) 백엔드로
# 처리되는데, akshare 일부 함수(stock_news_em 등)가 쓰는 r"　" 정규식을 RE2가
# 거부해 ArrowInvalid가 발생한다. 레거시 object 문자열(파이썬 re)로 되돌려 회피한다.
pd.set_option("future.infer_string", False)

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

SENT_IDS_FILE     = BASE_DIR / "data" / "sent_ids.json"
WATCHLIST_FILE    = BASE_DIR / "data" / "watchlist.json"
STOCK_DB_FILE     = BASE_DIR / "data" / "stock_db.json"
PREDICTION_LOG_FILE = BASE_DIR / "data" / "prediction_log.jsonl"
BACKTEST_LOG_FILE = BASE_DIR / "data" / "backtest_log.jsonl"
RESEARCH_STATE_FILE = BASE_DIR / "data" / "market_research.json"
WATCHLIST_EVENTS_FILE = BASE_DIR / "data" / "watchlist_events.json"
NEWS_LOG_FILE     = BASE_DIR / "data" / "news_log.json"
PROMPT_DIR        = Path(os.environ.get("TRANSLATION_PROMPT_DIR", "prompts"))
if not PROMPT_DIR.is_absolute():
    PROMPT_DIR = BASE_DIR / PROMPT_DIR

# ── Ollama / 번역 ─────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# num_gpu 설정(-1=자동, 0=CPU 전용, N=오프로딩 레이어 수).
# 런타임 변경(/system gpu ...)은 세션 한정이며 재시작하면 이 값으로 되돌아간다.
OLLAMA_NUM_GPU = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
# /system gpu on 으로 켤 때 적용할 값(-1=자동 권장).
OLLAMA_GPU_ON_VALUE = int(os.environ.get("OLLAMA_GPU_ON_VALUE", "-1"))
TRANSLATION_ENABLED = _env_bool("TRANSLATION_ENABLED", "true")
TRANSLATION_MODEL = os.environ.get("TRANSLATION_MODEL", "gemma4:e4b")
TRANSLATION_TIMEOUT = int(os.environ.get("TRANSLATION_TIMEOUT", "120"))
TRANSLATION_NUM_PREDICT = int(os.environ.get("TRANSLATION_NUM_PREDICT", "4096"))
TRANSLATION_CONCURRENCY = int(os.environ.get("TRANSLATION_CONCURRENCY", "2"))

SENT_NEWS_RETENTION_DAYS = int(os.environ.get("SENT_NEWS_RETENTION_DAYS", "7"))
TELEGRAM_MESSAGE_LIMIT = 4096
NEWS_GLOBAL_LIMIT = int(os.environ.get("NEWS_GLOBAL_LIMIT", "3"))
NEWS_TRANSLATED_CONTENT_MAX_CHARS = max(
    1,
    int(os.environ.get("NEWS_TRANSLATED_CONTENT_MAX_CHARS", "150")),
)
NEWS_DIGEST_MESSAGE_MAX_CHARS = min(
    TELEGRAM_MESSAGE_LIMIT,
    max(2000, int(os.environ.get("NEWS_DIGEST_MESSAGE_MAX_CHARS", "3500"))),
)
NEWS_STOCK_LIMIT_PER_SYMBOL = int(os.environ.get("NEWS_STOCK_LIMIT_PER_SYMBOL", "3"))
NEWS_ENABLE_CLS = _env_bool("NEWS_ENABLE_CLS", "false")
NEWS_SOURCE_FETCH_TIMEOUT_SECONDS = float(
    os.environ.get("NEWS_SOURCE_FETCH_TIMEOUT_SECONDS", "45")
)
NEWS_SOURCE_ARTICLE_LIMIT = max(
    1,
    int(os.environ.get("NEWS_SOURCE_ARTICLE_LIMIT", "10")),
)


def _parse_global_source_keys() -> list[str]:
    """전역 뉴스 소스 우선순위 목록.

    NEWS_GLOBAL_SOURCES가 설정되면 그 목록이 전부다. 미설정이면 기본
    futu,em,sina에 NEWS_ENABLE_CLS=true일 때 cls를 덧붙인다(하위 호환).
    """
    raw = os.environ.get("NEWS_GLOBAL_SOURCES", "").strip()
    if raw:
        return [key.strip().lower() for key in raw.split(",") if key.strip()]
    keys = ["futu", "em", "sina", "gnews"]
    if NEWS_ENABLE_CLS:
        keys.append("cls")
    return keys


def _parse_rss_feeds() -> list[tuple[str, str]]:
    """NEWS_RSS_FEEDS='라벨|URL,라벨|URL' → [(라벨, URL), ...]"""
    raw = os.environ.get("NEWS_RSS_FEEDS", "").strip()
    feeds: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, _, url = chunk.partition("|")
        label, url = label.strip(), url.strip()
        if label and url.startswith("http"):
            feeds.append((label, url))
    return feeds


NEWS_GLOBAL_SOURCE_KEYS = _parse_global_source_keys()
NEWS_RSS_FEEDS = _parse_rss_feeds()
NEWS_SOURCE_FAILURE_THRESHOLD = int(os.environ.get("NEWS_SOURCE_FAILURE_THRESHOLD", "3"))
NEWS_SOURCE_COOLDOWN_MINUTES = int(os.environ.get("NEWS_SOURCE_COOLDOWN_MINUTES", "60"))
# 뉴스 메시지에 감성 점수 표기 여부와, 관심종목 부정 뉴스 경고 기준(-1~0).
NEWS_SENTIMENT_ENABLED = _env_bool("NEWS_SENTIMENT_ENABLED", "true")
NEWS_NEGATIVE_ALERT_THRESHOLD = float(os.environ.get("NEWS_NEGATIVE_ALERT_THRESHOLD", "-0.6"))
# /view 감성 뷰 집계에 사용할 최근 신호 일수.
VIEW_LOOKBACK_DAYS = int(os.environ.get("VIEW_LOOKBACK_DAYS", "3"))
# 한 주기에 처리할 관심종목 수. 기본값 0은 전체 종목을 조회해 한 묶음으로 보낸다.
# 양수로 지정하면 해당 개수만큼 여러 주기에 나눠 회전 처리한다.
STOCK_NEWS_BATCH_SIZE = int(os.environ.get("STOCK_NEWS_BATCH_SIZE", "0"))
# 배치 내 종목 간 외부 API 호출 사이에 둘 지연(초). 0이면 지연 없음.
STOCK_NEWS_FETCH_DELAY_SECONDS = float(os.environ.get("STOCK_NEWS_FETCH_DELAY_SECONDS", "0"))
# 한 주기에 처리할 전역 속보 소스 수. 기본값 0은 활성 소스 전체를 처리한다.
# 양수로 지정하면 해당 개수만큼 소스를 회전 처리할 수 있다.
GLOBAL_NEWS_BATCH_SIZE = int(os.environ.get("GLOBAL_NEWS_BATCH_SIZE", "0"))
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "5"))
STOCK_DB_ENABLED = _env_bool("STOCK_DB_ENABLED", "true")
# ── 시황 리서치(/research) ────────────────────────────
RESEARCH_ANALYSIS_PROMPT_FILE = PROMPT_DIR / "market_research_ko.txt"
RESEARCH_ANALYSIS_MODEL = os.environ.get("RESEARCH_ANALYSIS_MODEL", TRANSLATION_MODEL)
RESEARCH_ANALYSIS_ENABLED = _env_bool("RESEARCH_ANALYSIS_ENABLED", "true")
RESEARCH_ANALYSIS_TIMEOUT = max(
    30,
    int(os.environ.get("RESEARCH_ANALYSIS_TIMEOUT", "600")),
)
RESEARCH_NEWS_STOCK_LIMIT_PER_SYMBOL = int(
    os.environ.get("RESEARCH_NEWS_STOCK_LIMIT_PER_SYMBOL", "3")
)
RESEARCH_NEWS_MAX_ITEMS = int(
    os.environ.get("RESEARCH_NEWS_MAX_ITEMS", "3")
)
RESEARCH_NEWS_GLOBAL_LIMIT = int(
    os.environ.get("RESEARCH_NEWS_GLOBAL_LIMIT", "3")
)
RESEARCH_ANALYSIS_NUM_PREDICT = int(
    os.environ.get("RESEARCH_ANALYSIS_NUM_PREDICT", "2048")
)
RESEARCH_CPU_THREADS = max(
    1,
    int(os.environ.get("RESEARCH_CPU_THREADS", str(max(1, (os.cpu_count() or 4) // 3)))),
)
NON_URGENT_WORKER_COUNT = max(1, int(os.environ.get("NON_URGENT_WORKER_COUNT", "1")))
RESEARCH_REMOVE_RELEVANCE_THRESHOLD = min(
    1.0,
    max(
        0.0,
        float(os.environ.get("RESEARCH_REMOVE_RELEVANCE_THRESHOLD", "0.35")),
    ),
)
# 시장뷰 분석 강화: bull/bear 검증 패스, 분석 이력 메모리
RESEARCH_VERIFICATION_ENABLED = _env_bool("RESEARCH_VERIFICATION_ENABLED", "true")
RESEARCH_VERIFICATION_PROMPT_FILE = PROMPT_DIR / "market_research_verify_ko.txt"
RESEARCH_HISTORY_LIMIT = int(os.environ.get("RESEARCH_HISTORY_LIMIT", "5"))
# 강세 섹터 구성종목을 리서치 후보군에 추가
RESEARCH_SECTOR_CANDIDATES_ENABLED = _env_bool("RESEARCH_SECTOR_CANDIDATES_ENABLED", "true")
RESEARCH_SECTOR_CANDIDATE_LIMIT = int(os.environ.get("RESEARCH_SECTOR_CANDIDATE_LIMIT", "10"))
# 동화순 问财 자연어 스크리닝(비공식 API, pywencai 별도 설치 필요)
WENCAI_ENABLED = _env_bool("WENCAI_ENABLED", "false")
WENCAI_CANDIDATE_LIMIT = int(os.environ.get("WENCAI_CANDIDATE_LIMIT", "10"))

# 정량 컨텍스트(시세·자금흐름·섹터·인기순위·涨停·용호방)
QUANT_CONTEXT_ENABLED = _env_bool("QUANT_CONTEXT_ENABLED", "true")
QUANT_CACHE_TTL_MINUTES = int(os.environ.get("QUANT_CACHE_TTL_MINUTES", "10"))
QUANT_SECTOR_TOP_N = int(os.environ.get("QUANT_SECTOR_TOP_N", "5"))
QUANT_FAILURE_COOLDOWN_MINUTES = int(os.environ.get("QUANT_FAILURE_COOLDOWN_MINUTES", "15"))
# 동방재부 인기순위 API는 해외 IP에서 차단되므로 기본 비활성.
QUANT_HOT_RANK_ENABLED = _env_bool("QUANT_HOT_RANK_ENABLED", "false")

# 최근 뉴스 로그(마감 브리핑 요약 입력)
NEWS_LOG_RETENTION_DAYS = int(os.environ.get("NEWS_LOG_RETENTION_DAYS", "30"))
# Source-to-market mapping for the market sentiment dashboard.  Values are
# ISO-like market keys (CN, HK, US, KR, JP, ...); an unmapped source is kept as
# "OTHER" instead of being silently mixed into another market.
def _parse_market_map() -> dict[str, str]:
    raw = os.environ.get("NEWS_SOURCE_MARKETS", "").strip()
    mapping: dict[str, str] = {
        "futu": "CN",
        "em": "CN",
        "sina": "CN",
        "ths": "CN",
        "cls": "CN",
        "stock": "CN",
    }
    for item in raw.split(","):
        source, separator, market = item.rpartition(":")
        if not separator:
            continue
        source, market = source.strip().lower(), market.strip().upper()
        if source and market:
            mapping[source] = market
    return mapping


NEWS_SOURCE_MARKETS = _parse_market_map()
MARKET_CHART_LOOKBACK_DAYS = int(os.environ.get("MARKET_CHART_LOOKBACK_DAYS", "7"))
MARKET_CHART_MIN_ARTICLES = int(os.environ.get("MARKET_CHART_MIN_ARTICLES", "6"))
MARKET_CHART_MIN_DAYS = int(os.environ.get("MARKET_CHART_MIN_DAYS", "3"))
MARKET_CHART_MARKETS = frozenset(
    market.strip().upper()
    for market in os.environ.get("MARKET_CHART_MARKETS", "CN,HK,US,KR").split(",")
    if market.strip()
)


def _parse_market_backfill_queries() -> dict[str, str]:
    raw = os.environ.get("NEWS_MARKET_BACKFILL_QUERIES", "").strip()
    defaults = {
        "CN": "China stock market",
        "HK": "Hong Kong stock market",
        "US": "US stock market",
        "KR": "Korea stock market",
        "JP": "Japan stock market",
        "EU": "European stock market",
        "RU": "Russia stock market",
        "TW": "Taiwan stock market",
    }
    if not raw:
        return defaults
    queries: dict[str, str] = {}
    for item in raw.split(","):
        market, separator, query = item.partition("|")
        market, query = market.strip().upper(), query.strip()
        if separator and market and query:
            queries[market] = query
    return queries


NEWS_MARKET_BACKFILL_QUERIES = _parse_market_backfill_queries()

# 모닝/마감 브리핑과 주간 성적표(호스트 현지 시각 기준 cron)
BRIEFING_MORNING_ENABLED = _env_bool("BRIEFING_MORNING_ENABLED", "true")
BRIEFING_MORNING_HOUR = int(os.environ.get("BRIEFING_MORNING_HOUR", "8"))
BRIEFING_MORNING_MINUTE = int(os.environ.get("BRIEFING_MORNING_MINUTE", "50"))
BRIEFING_EVENING_ENABLED = _env_bool("BRIEFING_EVENING_ENABLED", "true")
BRIEFING_EVENING_HOUR = int(os.environ.get("BRIEFING_EVENING_HOUR", "17"))
BRIEFING_EVENING_MINUTE = int(os.environ.get("BRIEFING_EVENING_MINUTE", "40"))
BRIEFING_LLM_ENABLED = _env_bool("BRIEFING_LLM_ENABLED", "true")
BRIEFING_NEWS_MAX_ITEMS = int(os.environ.get("BRIEFING_NEWS_MAX_ITEMS", "5"))
BRIEFING_PROMPT_FILE = PROMPT_DIR / "briefing_ko.txt"
# 미설정 시 리서치 모델·타임아웃을 따른다.
BRIEFING_MODEL = os.environ.get("BRIEFING_MODEL", RESEARCH_ANALYSIS_MODEL)
BRIEFING_TIMEOUT = int(os.environ.get("BRIEFING_TIMEOUT", "120"))
SCORECARD_ENABLED = _env_bool("SCORECARD_ENABLED", "true")
SCORECARD_DAY_OF_WEEK = os.environ.get("SCORECARD_DAY_OF_WEEK", "sat")
SCORECARD_HOUR = int(os.environ.get("SCORECARD_HOUR", "10"))
SCORECARD_LOOKBACK_DAYS = int(os.environ.get("SCORECARD_LOOKBACK_DAYS", "30"))


def _parse_allowed_chat_ids() -> frozenset[int]:
    raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            logging.getLogger(__name__).warning(
                "ALLOWED_CHAT_IDS에 숫자가 아닌 값이 있어 무시합니다: %s", chunk
            )
    return frozenset(ids)


# 비어 있으면 모두 허용(기존 동작). 채우면 해당 chat_id에서만 명령을 받는다.
ALLOWED_CHAT_IDS = _parse_allowed_chat_ids()
HELP_TEXT = (
    "<b>명령어 안내</b>\n\n"
    "/market [일수] — 국가별 뉴스 감성\n"
    "/menu · /list — 관심종목 관리·목록\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/view [종목코드] — 종목 감성\n"
    "/score [backtest] — 신호 성과\n"
    "/research show|set|run|clear — 리서치\n"
    "/briefing morning|evening|scorecard — 브리핑\n"
    "/stockdb build · /system — 관리\n\n"
    "종목코드 예: 중국 600519 · 홍콩 09988"
)
