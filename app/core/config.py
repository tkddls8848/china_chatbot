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
TRANSLATION_TIMEOUT = int(os.environ.get("TRANSLATION_TIMEOUT", "60"))
TRANSLATION_NUM_PREDICT = int(os.environ.get("TRANSLATION_NUM_PREDICT", "4096"))
TRANSLATION_CONCURRENCY = int(os.environ.get("TRANSLATION_CONCURRENCY", "2"))

SENT_NEWS_MAX_IDS = int(os.environ.get("SENT_NEWS_MAX_IDS", "0"))
SENT_NEWS_RETENTION_DAYS = int(os.environ.get("SENT_NEWS_RETENTION_DAYS", "7"))
TELEGRAM_MESSAGE_LIMIT = 4096
NEWS_GLOBAL_LIMIT = int(os.environ.get("NEWS_GLOBAL_LIMIT", "3"))
NEWS_STOCK_LIMIT_PER_SYMBOL = int(os.environ.get("NEWS_STOCK_LIMIT_PER_SYMBOL", "3"))
NEWS_ENABLE_CLS = _env_bool("NEWS_ENABLE_CLS", "false")
NEWS_SOURCE_FETCH_TIMEOUT_SECONDS = float(
    os.environ.get("NEWS_SOURCE_FETCH_TIMEOUT_SECONDS", "45")
)


def _parse_global_source_keys() -> list[str]:
    """전역 뉴스 소스 우선순위 목록.

    NEWS_GLOBAL_SOURCES가 설정되면 그 목록이 전부다. 미설정이면 기본
    futu,em,sina에 NEWS_ENABLE_CLS=true일 때 cls를 덧붙인다(하위 호환).
    """
    raw = os.environ.get("NEWS_GLOBAL_SOURCES", "").strip()
    if raw:
        return [key.strip().lower() for key in raw.split(",") if key.strip()]
    keys = ["futu", "em", "sina"]
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
# 한 주기에 처리할 관심종목 수. 0 이하면 전체를 한 번에 처리(기존 동작).
# 전체 종목을 매 주기 일괄 요청/번역하지 않고 여러 주기에 나눠 회전 처리해 부하를 분산한다.
STOCK_NEWS_BATCH_SIZE = int(os.environ.get("STOCK_NEWS_BATCH_SIZE", "3"))
# 배치 내 종목 간 외부 API 호출 사이에 둘 지연(초). 0이면 지연 없음.
STOCK_NEWS_FETCH_DELAY_SECONDS = float(os.environ.get("STOCK_NEWS_FETCH_DELAY_SECONDS", "0"))
# 한 주기에 처리할 전역 속보 소스(CLS/Futu) 수. 1이면 매 주기 한 소스씩 번갈아 처리.
# 0 이하이면 매 주기 전체(CLS+Futu)를 처리(기존 동작).
GLOBAL_NEWS_BATCH_SIZE = int(os.environ.get("GLOBAL_NEWS_BATCH_SIZE", "1"))
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "5"))
STOCK_DB_ENABLED = _env_bool("STOCK_DB_ENABLED", "true")


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
    "<b>사용 가능한 명령어</b>\n\n"
    "/start — 봇 소개와 사용 가능한 경로 보기\n"
    "/menu — 관심종목 관리 (삭제)\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/list — 관심종목 목록 확인\n"
    "/view — 관심종목 뉴스 감성 뷰\n"
    "/view 종목코드 — 종목별 상세 뷰\n"
    "/score — 감성 신호 적중률 채점\n"
    "/score backtest — 백필 신호 채점\n"
    "/stockdb build — 종목 코드·이름 목록 갱신\n"
    "/system — 시스템 상태 보기\n"
    "/system gpu on|off — Ollama GPU 가속 켜기/끄기\n"
    "/system gpu 레이어수 — GPU 오프로딩 레이어 수 지정\n"
    "/help — 도움말\n\n"
    "종목코드 형식:\n"
    "  • A주 상해: 6자리 (예: 600519)\n"
    "  • A주 심천: 6자리 (예: 300750)\n"
    "  • 홍콩: 5자리 (예: 09988)"
)
