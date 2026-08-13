"""환경 변수 로딩과 전역 설정 상수.

설정 저장 방침:
  - `.env` = 비밀값과 운영자가 조정하는 설정. 시작 시 1회, 이 모듈에서만 읽는다.
  - 운영자가 조정하지 않는 설정 = 이 모듈의 리터럴 상수.
    다른 모듈은 여기서 상수를 import 하며 `os.environ`에 직접 접근하지 않는다.
  - `data/<기능키>/*.json` = 봇이 수집·축적하는 데이터(관심종목, 전송 이력,
    종목 DB 등)로, 소유 기능별 하위 디렉토리에 둔다. 설정값은 저장하지
    않는다.

import 시 .env 로딩과 로깅 설정이 한 번 수행된다.
"""

import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# AkShare 응답의 정규식 처리를 위해 object 문자열 방식을 사용한다.
pd.set_option("future.infer_string", False)

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


class ConfigurationError(RuntimeError):
    """설정값이 잘못되어 봇을 기동할 수 없을 때 발생한다."""


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
PROMPT_DIR        = BASE_DIR / "prompts"

# ── 번역 ──────────────────────────────────────────────
TRANSLATION_ENABLED = _env_bool("TRANSLATION_ENABLED", "true")
TRANSLATION_NUM_PREDICT = 1536
# 한 주기에 묶어 처리하는 기사가 늘어난 만큼 번역도 병렬로 돌린다. 소스별
# 준비 루프는 기사를 순차 처리하므로, 동시 실행 폭은 이 세마포어가 정한다.
TRANSLATION_CONCURRENCY = 3

# ── Cloudflare Workers AI ─────────────────────────────
# API 토큰은 .env에만 두고 커밋하지 않는다. 로그·예외에도 남기지 않는다.
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_AI_BASE_URL = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_TRANSLATION_MODEL = os.environ.get(
    "CLOUDFLARE_TRANSLATION_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8"
).strip()
# 시황 분석·브리핑용 모델. 미지정 시 번역과 같은 모델을 쓴다.
CLOUDFLARE_ANALYSIS_MODEL = (
    os.environ.get("CLOUDFLARE_ANALYSIS_MODEL", "").strip()
    or CLOUDFLARE_TRANSLATION_MODEL
)
CLOUDFLARE_TRANSLATION_TIMEOUT = 45
CLOUDFLARE_MAX_ATTEMPTS = 2
CLOUDFLARE_FAILURE_THRESHOLD = 3
CLOUDFLARE_FAILURE_COOLDOWN_SECONDS = 300


# /research 분석과 /market 다이제스트는 전용 플래그 없이 기능 키가 켜지면
# 항상 LLM을 쓴다. 그래서 자격증명 요구 여부는 FEATURES_ENABLED로 판단한다.
_LLM_FEATURE_KEYS = frozenset({"research", "market_sentiment"})


def _validate_cloudflare_credentials() -> None:
    """자격증명 없이 기동해서 첫 뉴스 주기에 전부 실패하는 일을 막는다."""
    if not (
        TRANSLATION_ENABLED
        or (FEATURES_ENABLED & _LLM_FEATURE_KEYS)
        or _env_bool("BRIEFING_LLM_ENABLED", "true")
    ):
        return
    missing = [
        name
        for name, value in (
            ("CLOUDFLARE_ACCOUNT_ID", CLOUDFLARE_ACCOUNT_ID),
            ("CLOUDFLARE_API_TOKEN", CLOUDFLARE_API_TOKEN),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "LLM 기능(번역·리서치·시황 다이제스트·브리핑)이 켜져 있으나 "
            f"{', '.join(missing)}이(가) .env에 비어 있습니다"
        )


_validate_cloudflare_credentials()

# ── 관리 웹(web_admin 기능) ───────────────────────────
# 봇 프로세스에 내장되는 관리용 웹 대시보드. FEATURES_ENABLED의 web_admin
# 키로 켜고 끄며, 봇을 제어하므로 WEB_ADMIN_PASSWORD를 지정해야만 기동한다.
WEB_ADMIN_HOST = os.environ.get("WEB_ADMIN_HOST", "127.0.0.1")
WEB_ADMIN_PORT = int(os.environ.get("WEB_ADMIN_PORT", "8787"))
WEB_ADMIN_USER = os.environ.get("WEB_ADMIN_USER", "admin")
WEB_ADMIN_PASSWORD = os.environ.get("WEB_ADMIN_PASSWORD", "")

SENT_NEWS_RETENTION_DAYS = 7
TELEGRAM_MESSAGE_LIMIT = 4096
# 소스 하나가 한 주기에 **번역**할 새 기사 수. Neurons를 쓰는 건 이 값이다
# (소스 6곳 기준 주기당 최대 36회 호출).
NEWS_GLOBAL_LIMIT = int(os.environ.get("NEWS_GLOBAL_LIMIT", "6"))
# 번역한 기사 중 소스 하나가 실제로 **송출**할 건수. impact가 높은 순으로
# 고르고 나머지는 텔레그램 메시지에서만 빠진다 — 번역·감성 결과는 그대로
# news_log·prediction_log에 남아 /view·/market·signal_scoring이 읽는다.
# 탈락분을 다시 집어 재번역하지 않도록 확정(confirm)까지 마친다.
NEWS_DIGEST_SEND_LIMIT = max(
    1,
    int(os.environ.get("NEWS_DIGEST_SEND_LIMIT", "3")),
)
NEWS_DIGEST_MESSAGE_MAX_CHARS = 3500
NEWS_SOURCE_FETCH_TIMEOUT_SECONDS = 45.0
NEWS_LIVE_MAX_AGE_HOURS = 48
# 소스 한 곳을 얼마나 깊이 읽을지. 하루 기사 수량을 정하는 상한은 번역
# 상한(NEWS_GLOBAL_LIMIT)이 아니라 이 값이다 — 여기서 잘린 기사는 다음
# 주기에도 목록에 남지 않으면 영영 보이지 않는다. gnews는 이 값을 시장
# 수로, gnews_us·gnews_kr은 질의 수로 다시 나눠 쓴다.
NEWS_SOURCE_ARTICLE_LIMIT = max(
    1,
    int(os.environ.get("NEWS_SOURCE_ARTICLE_LIMIT", "30")),
)


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


NEWS_GLOBAL_SOURCE_KEYS = [
    key.strip().lower()
    for key in os.environ.get(
        "NEWS_GLOBAL_SOURCES",
        "futu,sina,gnews,gnews_us,gnews_kr",
    ).split(",")
    if key.strip()
]
NEWS_RSS_FEEDS = _parse_rss_feeds()
NEWS_SOURCE_FAILURE_THRESHOLD = 3
NEWS_SOURCE_COOLDOWN_MINUTES = 60
# 뉴스 메시지에 감성 점수 표기 여부와, 관심종목 부정 뉴스 경고 기준(-1~0).
NEWS_SENTIMENT_ENABLED = _env_bool("NEWS_SENTIMENT_ENABLED", "true")
NEWS_NEGATIVE_ALERT_THRESHOLD = -0.6
# /view 감성 뷰 집계에 사용할 최근 신호 일수.
VIEW_LOOKBACK_DAYS = 3
# 뉴스 주기. 짧게 돌려 조금씩 보내는 대신 텀을 늘려 한 번에 많이 묶는다.
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "20"))
# ── 시황 리서치(/research) ────────────────────────────
RESEARCH_ANALYSIS_PROMPT_FILE = PROMPT_DIR / "market_research_ko.txt"
RESEARCH_ANALYSIS_TIMEOUT = 600
RESEARCH_NEWS_MAX_ITEMS = 16
RESEARCH_NEWS_GLOBAL_LIMIT = 8
# 분석 payload에 넣을 기사 본문 길이 상한. 제목만으로는 촉매·수치를 읽을 수
# 없어 분석이 얕아지므로 본문을 함께 넣는다. 16건 × 600자에 후보 24개·정량·
# 이력까지 상한을 가득 채우면 입력이 약 22,000토큰(보수 추정)이고, 출력 예약
# 4,096을 더해 약 26,000으로 컨텍스트 32,768의 79% 선이다. 이 값이나
# RESEARCH_NEWS_MAX_ITEMS·RESEARCH_MAX_CANDIDATES를 올릴 때는 남은 21%를
# 어디까지 쓰는지 다시 계산한다 — 넘기면 응답이 중간에서 잘려 파싱이 실패한다.
RESEARCH_NEWS_CONTENT_MAX_CHARS = 600
# 리서치 뉴스 수집에서 균형을 맞출 시장 순서. 소스 우선순위대로 뽑으면 첫 소스
# (중화권)가 상한을 독식해 미국·한국 뉴스가 분석 입력에 들어가지 못한다.
# 여기 적힌 시장끼리 라운드로빈으로 뽑고, 목록 밖 시장은 마지막에 채운다.
RESEARCH_NEWS_MARKETS = ("CN", "US", "KR")
# 분석 결과는 JSON 한 덩어리로 오므로 상한에 걸리면 문자열 중간에서 잘려
# 파싱이 실패한다. 후보 수(RESEARCH_MAX_CANDIDATES)를 늘리면 함께 올린다.
RESEARCH_ANALYSIS_NUM_PREDICT = 4096
RESEARCH_MAX_CANDIDATES = 24
# 뉴스 본문 종목명 매칭에서 버릴 '흔한 영문 토큰'의 기준(이 수보다 많은 종목이
# 공유하는 토큰은 사용하지 않는다).
RESEARCH_NAME_TOKEN_MAX_FREQUENCY = 15
RESEARCH_MAX_NEW_ACTIONS = 6
# 후보 상한 중 시장별 발굴에 남겨 둘 자리.
RESEARCH_DISCOVERY_RESERVED_SLOTS = 8
NON_URGENT_WORKER_COUNT = 3
# 뉴스 주기가 도는 동안 비긴급 LLM 작업을 보류할 최대 시간(초). 한도를 넘으면
# 굶지 않도록 그대로 진행한다. 0이면 보류하지 않는다.
NON_URGENT_DEFER_TIMEOUT_SECONDS = 180
RESEARCH_REMOVE_RELEVANCE_THRESHOLD = 0.35
RESEARCH_HISTORY_LIMIT = 5
# 강세 섹터 구성종목을 리서치 후보군에 추가
RESEARCH_SECTOR_CANDIDATES_ENABLED = _env_bool("RESEARCH_SECTOR_CANDIDATES_ENABLED", "true")
RESEARCH_SECTOR_CANDIDATE_LIMIT = 14
# 미국 후보 발굴: Yahoo Finance 프리셋 스크리너(yfinance.screen).
RESEARCH_US_CANDIDATES_ENABLED = _env_bool("RESEARCH_US_CANDIDATES_ENABLED", "true")
RESEARCH_US_CANDIDATE_LIMIT = 12
RESEARCH_US_SCREENERS = ("day_gainers", "most_actives")
# 한국 후보 발굴: FinanceDataReader KRX 시세 목록의 등락률 상위.
RESEARCH_KR_CANDIDATES_ENABLED = _env_bool("RESEARCH_KR_CANDIDATES_ENABLED", "true")
RESEARCH_KR_CANDIDATE_LIMIT = 12
# 거래대금(원) 하한. 급등만 보고 잡주를 추천 후보로 올리지 않기 위한 필터.
RESEARCH_KR_MIN_TRADING_VALUE = 5000000000.0

# 정량 컨텍스트(시세·자금흐름·섹터·涨停·용호방)
QUANT_CACHE_TTL_MINUTES = 10
QUANT_SECTOR_TOP_N = 5
QUANT_FAILURE_COOLDOWN_MINUTES = 15

# 최근 뉴스 로그(마감 브리핑 요약 입력)
NEWS_LOG_RETENTION_DAYS = 30
# Source-to-market mapping for the market sentiment dashboard.  Values are
# ISO-like market keys (CN, HK, US, KR, JP, ...); an unmapped source is kept as
# "OTHER" instead of being silently mixed into another market.
def _parse_market_map() -> dict[str, str]:
    raw = os.environ.get("NEWS_SOURCE_MARKETS", "").strip()
    mapping: dict[str, str] = {
        "futu": "CN",
        "sina": "CN",
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
MARKET_CHART_LOOKBACK_DAYS = 7
MARKET_CHART_MIN_ARTICLES = 6
MARKET_CHART_MIN_DAYS = 3
MARKET_CHART_BACKFILL_DAYS_PER_REQUEST = 7
MARKET_CHART_MARKETS = frozenset({"CN", "HK", "US", "KR"})

# 일별 감성 다이제스트는 하루치 헤드라인을 한 번에 분석한다.
MARKET_DIGEST_FILE = DATA_DIR / "market_sentiment" / "daily_digest.json"
MARKET_DIGEST_PROMPT_FILE = PROMPT_DIR / "market_digest_ko.txt"
MARKET_DIGEST_ARTICLES_PER_DAY = 40
# 표본이 이보다 적은 날은 계산하지 않는다. 3건짜리 하루를 20건짜리 하루와 같은
# 무게로 그리면 차트가 다시 출렁인다.
MARKET_DIGEST_MIN_ARTICLES = 5
# `/market` 최대 조회 범위(30일)와 맞춘다. 그보다 오래된 항목은 차트가 읽지 않는다.
MARKET_DIGEST_RETENTION_DAYS = 30
# 요청당 LLM 호출 상한. 40회 ≈ 350 Neurons.
MARKET_DIGEST_MAX_CALLS_PER_REQUEST = 40
MARKET_DIGEST_NUM_PREDICT = 512
MARKET_DIGEST_TIMEOUT = 60
# 감성 건수의 합이 입력 헤드라인 수와 크게 다르면 그 건수를 버린다(그날의
# sentiment·summary는 남긴다). 허용 오차 = max(1, ceil(헤드라인 수 × 이 비율)).
# 이 비율은 `MARKET_DIGEST_ARTICLES_PER_DAY`와 함께 봐야 한다. 모델의 세기
# 오차는 목록이 길어질수록 비례 이상으로 커진다 — 20건 시절 실측은 93일 중
# 78일이 오차 0, 최대 2였지만 35~40건에서는 5까지 벌어졌다. 상한을 40으로
# 올리면서 0.1(35건 → 허용 4)로는 정상 응답이 탈락했다.
MARKET_DIGEST_COUNT_TOLERANCE_RATIO = 0.2


# ── Polymarket 거시 위험선호 컨센서스(섀도 파일럿) ────
# Gamma API는 인증이 필요 없고 LLM을 쓰지 않으므로 추가 Neurons는 0/일이다.
# 값은 국가별 뉴스 감성 점수에 절대 합산하지 않고 `/market` 하단 별도 패널에만
# 그린다. 수집과 표시를 분리해 두는 이유는 30일 섀도 파일럿 때문이다 —
# 수집만 켜 두고(ENABLED) 승격 게이트를 통과할 때까지 패널은 끈다(PANEL).
POLYMARKET_CONSENSUS_FILE = DATA_DIR / "market_sentiment" / "polymarket_consensus.json"
POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"
POLYMARKET_ENABLED = _env_bool("POLYMARKET_ENABLED", "false")
POLYMARKET_PANEL_ENABLED = _env_bool("POLYMARKET_PANEL_ENABLED", "false")
POLYMARKET_TIMEOUT = max(5, int(os.environ.get("POLYMARKET_TIMEOUT", "20")))
# 선택 게이트. 유동성이 얕은 계약은 하루 변화가 호가 한 번에 흔들려 컨센서스가
# 아니라 잡음이 된다. 실측 기준(volume 10,000 · liquidity 1,000)을 기본값으로 둔다.
POLYMARKET_MIN_VOLUME = float(os.environ.get("POLYMARKET_MIN_VOLUME", "10000"))
POLYMARKET_MIN_LIQUIDITY = float(os.environ.get("POLYMARKET_MIN_LIQUIDITY", "1000"))
# 승격 게이트의 "median spread 5%p 이하"와 같은 기준을 수집 단계에서도 쓴다.
POLYMARKET_MAX_SPREAD = max(
    0.0,
    float(os.environ.get("POLYMARKET_MAX_SPREAD", "0.05")),
)
# 만기가 너무 먼 계약은 하루 단위로 거의 움직이지 않아 신호를 희석한다.
POLYMARKET_MAX_HORIZON_DAYS = max(
    1,
    int(os.environ.get("POLYMARKET_MAX_HORIZON_DAYS", "365")),
)
# 30일 파일럿의 일별 변화를 계산하려면 하루 전 스냅숏이 남아 있어야 한다.
POLYMARKET_RETENTION_DAYS = max(
    2,
    int(os.environ.get("POLYMARKET_RETENTION_DAYS", "31")),
)


NEWS_MARKET_BACKFILL_QUERIES = {
    "CN": "China stock market",
    "HK": "Hong Kong stock market",
    "US": "US stock market",
    "KR": "Korea stock market",
    "JP": "Japan stock market",
    "EU": "European stock market",
    "RU": "Russia stock market",
    "TW": "Taiwan stock market",
}

# 모닝/마감 브리핑과 관심종목 편입·편출 성과표(호스트 현지 시각 기준 cron)
BRIEFING_MORNING_ENABLED = _env_bool("BRIEFING_MORNING_ENABLED", "true")
BRIEFING_MORNING_HOUR = int(os.environ.get("BRIEFING_MORNING_HOUR", "8"))
BRIEFING_MORNING_MINUTE = int(os.environ.get("BRIEFING_MORNING_MINUTE", "50"))
BRIEFING_EVENING_ENABLED = _env_bool("BRIEFING_EVENING_ENABLED", "true")
BRIEFING_EVENING_HOUR = int(os.environ.get("BRIEFING_EVENING_HOUR", "17"))
BRIEFING_EVENING_MINUTE = int(os.environ.get("BRIEFING_EVENING_MINUTE", "40"))
BRIEFING_LLM_ENABLED = _env_bool("BRIEFING_LLM_ENABLED", "true")
BRIEFING_NEWS_MAX_ITEMS = 14
BRIEFING_PROMPT_FILE = PROMPT_DIR / "briefing_ko.txt"
BRIEFING_TIMEOUT = 180
# 코멘트 출력 예약 토큰. 헤드라인을 늘린 만큼 코멘트도 길게 받는다.
BRIEFING_NUM_PREDICT = 1024


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
