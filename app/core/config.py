"""환경 변수 로딩과 전역 설정 상수.

설정 저장 방침:
  - `.env` = 모든 설정의 유일한 원본. 시작 시 1회, 이 모듈에서만 읽는다.
    다른 모듈은 여기서 상수를 import 하며 `os.environ`에 직접 접근하지 않는다.
  - `data/<기능키>/*.json` = 봇이 수집·축적하는 데이터(관심종목, 전송 이력,
    종목 DB 등)로, 소유 기능별 하위 디렉토리에 둔다. 설정값은 저장하지
    않는다. 런타임 변경(/system gpu ...)은 세션 한정이며 재시작하면
    `.env` 값으로 되돌아간다.

import 시 .env 로딩과 로깅 설정이 한 번 수행된다.
"""

import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# pandas 3.0부터 문자열 추론 방식이 바뀌어 일부 AkShare 응답의 정규식 처리가
# 실패할 수 있으므로 레거시 object 문자열 방식으로 고정한다.
pd.set_option("future.infer_string", False)

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


_DEFAULT_FEATURES = (
    "instruments,quant,watchlist,news,market_sentiment,"
    "research,briefing,signal_scoring,system_admin,web_admin"
)
FEATURES_ENABLED = frozenset(
    key.strip()
    for key in os.environ.get("FEATURES_ENABLED", _DEFAULT_FEATURES).split(",")
    if key.strip()
)

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

# 데이터는 코드와 같은 기준으로 소유 기능 키의 하위 디렉토리에 둔다.
# (news/, watchlist/, instruments/, signal_scoring/, research/, runtime/)
DATA_DIR          = BASE_DIR / "data"
SENT_IDS_FILE     = DATA_DIR / "news" / "sent_ids.json"
NEWS_LOG_FILE     = DATA_DIR / "news" / "news_log.json"
WATCHLIST_FILE    = DATA_DIR / "watchlist" / "watchlist.json"
WATCHLIST_EVENTS_FILE = DATA_DIR / "watchlist" / "watchlist_events.json"
STOCK_DB_FILE     = DATA_DIR / "instruments" / "stock_db.json"
PREDICTION_LOG_FILE = DATA_DIR / "signal_scoring" / "prediction_log.jsonl"
RESEARCH_STATE_FILE = DATA_DIR / "research" / "market_research.json"
RUNTIME_LOCK_FILE = DATA_DIR / "runtime" / "bot.lock"
PROMPT_DIR        = Path(os.environ.get("TRANSLATION_PROMPT_DIR", "prompts"))
if not PROMPT_DIR.is_absolute():
    PROMPT_DIR = BASE_DIR / PROMPT_DIR

# ── Ollama / 번역 ─────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# num_gpu 설정(-1=자동, 0=CPU 전용, N=오프로딩 레이어 수).
# 런타임 변경(/system gpu ...)은 세션 한정이며 재시작하면 이 값으로 되돌아간다.
OLLAMA_NUM_GPU = int(os.environ.get("OLLAMA_NUM_GPU", "-1"))
# /system gpu on 으로 켤 때 적용할 값(-1=자동 권장).
OLLAMA_GPU_ON_VALUE = int(os.environ.get("OLLAMA_GPU_ON_VALUE", "-1"))
TRANSLATION_ENABLED = _env_bool("TRANSLATION_ENABLED", "true")
TRANSLATION_MODEL = os.environ.get("TRANSLATION_MODEL", "qwen3.5:4b")
TRANSLATION_TIMEOUT = int(os.environ.get("TRANSLATION_TIMEOUT", "120"))
TRANSLATION_NUM_PREDICT = int(os.environ.get("TRANSLATION_NUM_PREDICT", "1024"))
# Ollama는 기본적으로 모델당 요청을 직렬 처리하므로 동시 요청을 늘려도
# 큐만 깊어진다. 늘리려면 Ollama의 OLLAMA_NUM_PARALLEL을 함께 올린다.
TRANSLATION_CONCURRENCY = int(os.environ.get("TRANSLATION_CONCURRENCY", "1"))

# ── 관리 웹(web_admin 기능) ───────────────────────────
# 봇 프로세스에 내장되는 관리용 웹 대시보드. FEATURES_ENABLED의 web_admin
# 키로 켜고 끄며, 봇을 제어하므로 WEB_ADMIN_PASSWORD를 지정해야만 기동한다.
WEB_ADMIN_HOST = os.environ.get("WEB_ADMIN_HOST", "127.0.0.1")
WEB_ADMIN_PORT = int(os.environ.get("WEB_ADMIN_PORT", "8787"))
WEB_ADMIN_USER = os.environ.get("WEB_ADMIN_USER", "admin")
WEB_ADMIN_PASSWORD = os.environ.get("WEB_ADMIN_PASSWORD", "")

SENT_NEWS_RETENTION_DAYS = int(os.environ.get("SENT_NEWS_RETENTION_DAYS", "7"))
TELEGRAM_MESSAGE_LIMIT = 4096
NEWS_GLOBAL_LIMIT = int(os.environ.get("NEWS_GLOBAL_LIMIT", "3"))
NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS = max(
    1,
    int(os.environ.get("NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS", "180")),
)
NEWS_DIGEST_MESSAGE_MAX_CHARS = min(
    TELEGRAM_MESSAGE_LIMIT,
    max(2000, int(os.environ.get("NEWS_DIGEST_MESSAGE_MAX_CHARS", "3500"))),
)
NEWS_ENABLE_CLS = _env_bool("NEWS_ENABLE_CLS", "false")
NEWS_SOURCE_FETCH_TIMEOUT_SECONDS = float(
    os.environ.get("NEWS_SOURCE_FETCH_TIMEOUT_SECONDS", "45")
)
NEWS_LIVE_MAX_AGE_HOURS = max(
    1,
    int(os.environ.get("NEWS_LIVE_MAX_AGE_HOURS", "48")),
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
    keys = ["futu", "sina", "gnews", "gnews_us", "gnews_kr"]
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
# 한 주기에 처리할 전역 속보 소스 수. 기본값 0은 활성 소스 전체를 처리한다.
# 양수로 지정하면 해당 개수만큼 소스를 회전 처리할 수 있다.
GLOBAL_NEWS_BATCH_SIZE = int(os.environ.get("GLOBAL_NEWS_BATCH_SIZE", "0"))
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "5"))
STOCK_DB_ENABLED = _env_bool("STOCK_DB_ENABLED", "true")
# ── 시황 리서치(/research) ────────────────────────────
RESEARCH_ANALYSIS_PROMPT_FILE = PROMPT_DIR / "market_research_ko.txt"
# 번역과 같은 모델을 쓴다. 다른 모델로 나눠 러너를 분리하는 방식은 시도했다가
# 되돌렸다. 두 러너가 메모리 때문에 공존하지 못하고 번갈아 축출되면서, 전환
# 때마다 러너를 재적재해 오히려 느려졌다. 경합은 core.workers의 긴급 구간
# 게이트로 막는다(뉴스 주기 중에는 리서치 분석 시작을 보류).
RESEARCH_ANALYSIS_MODEL = os.environ.get("RESEARCH_ANALYSIS_MODEL", "qwen3.5:4b")
RESEARCH_ANALYSIS_ENABLED = _env_bool("RESEARCH_ANALYSIS_ENABLED", "true")
RESEARCH_ANALYSIS_TIMEOUT = max(
    30,
    int(os.environ.get("RESEARCH_ANALYSIS_TIMEOUT", "600")),
)
RESEARCH_NEWS_MAX_ITEMS = int(
    os.environ.get("RESEARCH_NEWS_MAX_ITEMS", "6")
)
RESEARCH_NEWS_GLOBAL_LIMIT = int(
    os.environ.get("RESEARCH_NEWS_GLOBAL_LIMIT", "3")
)
# 분석 payload에 넣을 기사 본문 길이 상한. 중국어 원문 기준 6건 × 260자가
# RESEARCH_CTX_MAX(12288)의 한계선이므로 여유를 두고 240으로 잡는다.
RESEARCH_NEWS_CONTENT_MAX_CHARS = max(
    80,
    int(os.environ.get("RESEARCH_NEWS_CONTENT_MAX_CHARS", "240")),
)
# 리서치 분석 입력을 번역할지 여부. false면 번역 LLM 호출(기사당 1회)을 건너뛰고
# 원문을 그대로 넣는다. 분석 모델은 다국어를 읽으므로 결과 품질보다 실행 시간이
# 더 크게 걸리는 지점이라 기본값이 false다. 대신 번역 파이프라인이 함께 뽑던
# mentioned_stocks·theme_candidates·sentiment가 없어지므로, 후보 발굴은 뉴스
# 본문 종목명 매칭과 시장 데이터 발굴(섹터·스크리너·등락률)에 의존한다.
RESEARCH_TRANSLATE_NEWS = _env_bool("RESEARCH_TRANSLATE_NEWS", "false")
# 리서치 뉴스 수집에서 균형을 맞출 시장 순서. 소스 우선순위대로 뽑으면 첫 소스
# (중화권)가 상한을 독식해 미국·한국 뉴스가 분석 입력에 들어가지 못한다.
# 여기 적힌 시장끼리 라운드로빈으로 뽑고, 목록 밖 시장은 마지막에 채운다.
RESEARCH_NEWS_MARKETS = tuple(
    market.strip().upper()
    for market in os.environ.get("RESEARCH_NEWS_MARKETS", "CN,US,KR").split(",")
    if market.strip()
)
# 분석 결과는 JSON 한 덩어리로 오므로 상한에 걸리면 문자열 중간에서 잘려
# 파싱이 실패한다. 후보 수(RESEARCH_MAX_CANDIDATES)를 늘리면 함께 올린다.
RESEARCH_ANALYSIS_NUM_PREDICT = int(
    os.environ.get("RESEARCH_ANALYSIS_NUM_PREDICT", "2048")
)
RESEARCH_CTX_MIN = max(
    4096,
    int(os.environ.get("RESEARCH_CTX_MIN", "8192")),
)
RESEARCH_CTX_MAX = max(
    RESEARCH_CTX_MIN,
    int(os.environ.get("RESEARCH_CTX_MAX", "24576")),
)
RESEARCH_CTX_SAFETY_RATIO = max(
    1.0,
    float(os.environ.get("RESEARCH_CTX_SAFETY_RATIO", "1.20")),
)
RESEARCH_CPU_THREADS = max(
    1,
    int(os.environ.get("RESEARCH_CPU_THREADS", str(max(1, (os.cpu_count() or 4) // 3)))),
)
RESEARCH_MAX_CANDIDATES = max(
    1,
    int(os.environ.get("RESEARCH_MAX_CANDIDATES", "10")),
)
# 리서치 주제 키워드를 종목 '이름'과 대조해 만드는 후보. 근거가 이름 문자열
# 겹침뿐이라 15,000종목 상대로는 수백 개가 잡히면서 근거 있는 후보를 상한 밖으로
# 밀어낸다. 뉴스 근거·시장 데이터 발굴이 후보를 채우므로 기본 비활성이며,
# 켜더라도 LIMIT 개까지만 채운다(뉴스가 없는 날의 보조 수단).
RESEARCH_KEYWORD_CANDIDATES_ENABLED = _env_bool(
    "RESEARCH_KEYWORD_CANDIDATES_ENABLED", "false"
)
RESEARCH_KEYWORD_CANDIDATE_LIMIT = max(
    0,
    int(os.environ.get("RESEARCH_KEYWORD_CANDIDATE_LIMIT", "5")),
)
# 뉴스 테마 후보에서 LLM이 코드를 지정하지 않고 '이름 매칭'으로만 걸린 후보의
# 상한. 위와 같은 이유로 제한한다(LLM이 코드를 명시한 후보는 제한하지 않는다).
RESEARCH_THEME_PATTERN_CANDIDATE_LIMIT = max(
    0,
    int(os.environ.get("RESEARCH_THEME_PATTERN_CANDIDATE_LIMIT", "5")),
)
# 뉴스 본문 종목명 매칭에서 버릴 '흔한 영문 토큰'의 기준(이 수보다 많은 종목이
# 공유하는 토큰은 사용하지 않는다). 종목 DB 실측상 tech=29, energy=83인 반면
# apple=1, semiconductor=6이라 15면 일반 단어만 걸러진다.
RESEARCH_NAME_TOKEN_MAX_FREQUENCY = max(
    1,
    int(os.environ.get("RESEARCH_NAME_TOKEN_MAX_FREQUENCY", "15")),
)
RESEARCH_MAX_NEW_ACTIONS = max(
    0,
    int(os.environ.get("RESEARCH_MAX_NEW_ACTIONS", "4")),
)
# 후보 universe 상한 중 시장별 발굴(섹터·미국 스크리너·한국 등락률)에 남겨 둘
# 자리. 0이면 뉴스·키워드 후보가 상한을 채웠을 때 발굴 후보가 들어가지 못한다.
RESEARCH_DISCOVERY_RESERVED_SLOTS = max(
    0,
    int(os.environ.get("RESEARCH_DISCOVERY_RESERVED_SLOTS", "3")),
)
NON_URGENT_WORKER_COUNT = max(1, int(os.environ.get("NON_URGENT_WORKER_COUNT", "3")))
# 뉴스 주기가 도는 동안 비긴급 LLM 작업을 보류할 최대 시간(초). 한도를 넘으면
# 굶지 않도록 그대로 진행한다. 0이면 보류하지 않는다.
NON_URGENT_DEFER_TIMEOUT_SECONDS = max(
    0,
    int(os.environ.get("NON_URGENT_DEFER_TIMEOUT_SECONDS", "180")),
)
RESEARCH_REMOVE_RELEVANCE_THRESHOLD = min(
    1.0,
    max(
        0.0,
        float(os.environ.get("RESEARCH_REMOVE_RELEVANCE_THRESHOLD", "0.35")),
    ),
)
# 시장뷰 분석 강화: bull/bear 검증 패스, 분석 이력 메모리
RESEARCH_VERIFICATION_ENABLED = _env_bool("RESEARCH_VERIFICATION_ENABLED", "false")
RESEARCH_VERIFICATION_PROMPT_FILE = PROMPT_DIR / "market_research_verify_ko.txt"
RESEARCH_HISTORY_LIMIT = int(os.environ.get("RESEARCH_HISTORY_LIMIT", "3"))
# 강세 섹터 구성종목을 리서치 후보군에 추가
RESEARCH_SECTOR_CANDIDATES_ENABLED = _env_bool("RESEARCH_SECTOR_CANDIDATES_ENABLED", "true")
RESEARCH_SECTOR_CANDIDATE_LIMIT = int(os.environ.get("RESEARCH_SECTOR_CANDIDATE_LIMIT", "10"))
# 동화순 问财 자연어 스크리닝(비공식 API, pywencai 별도 설치 필요)
WENCAI_ENABLED = _env_bool("WENCAI_ENABLED", "false")
WENCAI_CANDIDATE_LIMIT = int(os.environ.get("WENCAI_CANDIDATE_LIMIT", "10"))
# 미국 후보 발굴: Yahoo Finance 프리셋 스크리너(yfinance.screen).
RESEARCH_US_CANDIDATES_ENABLED = _env_bool("RESEARCH_US_CANDIDATES_ENABLED", "true")
RESEARCH_US_CANDIDATE_LIMIT = int(os.environ.get("RESEARCH_US_CANDIDATE_LIMIT", "8"))
RESEARCH_US_SCREENERS = tuple(
    name.strip()
    for name in os.environ.get(
        "RESEARCH_US_SCREENERS", "day_gainers,most_actives"
    ).split(",")
    if name.strip()
)
# 한국 후보 발굴: FinanceDataReader KRX 시세 목록의 등락률 상위.
RESEARCH_KR_CANDIDATES_ENABLED = _env_bool("RESEARCH_KR_CANDIDATES_ENABLED", "true")
RESEARCH_KR_CANDIDATE_LIMIT = int(os.environ.get("RESEARCH_KR_CANDIDATE_LIMIT", "8"))
# 거래대금(원) 하한. 급등만 보고 잡주를 추천 후보로 올리지 않기 위한 필터.
RESEARCH_KR_MIN_TRADING_VALUE = float(
    os.environ.get("RESEARCH_KR_MIN_TRADING_VALUE", "5000000000")
)

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
        "gnews_us": "US",
        "gnews_kr": "KR",
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
MARKET_CHART_BACKFILL_DAYS_PER_REQUEST = max(
    1,
    int(os.environ.get("MARKET_CHART_BACKFILL_DAYS_PER_REQUEST", "7")),
)
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
    "/score — 운영 신호 성과\n"
    "/research show|set|run|clear — 리서치\n"
    "/briefing morning|evening|scorecard — 브리핑\n"
    "/stockdb build · /system — 관리\n\n"
    "종목코드 예: 중국 600519 · 홍콩 09988"
)
