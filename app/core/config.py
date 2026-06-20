"""환경 변수 로딩과 전역 설정 상수.

다른 모듈은 이 모듈에서 상수를 가져온다. import 시 .env 로딩과 로깅 설정이
한 번 수행된다.
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
RESEARCH_STATE_FILE = BASE_DIR / "data" / "market_research.json"
RUNTIME_CONFIG_FILE = BASE_DIR / "data" / "runtime_config.json"
PROMPT_DIR        = Path(os.environ.get("TRANSLATION_PROMPT_DIR", "prompts"))
if not PROMPT_DIR.is_absolute():
    PROMPT_DIR = BASE_DIR / PROMPT_DIR
RESEARCH_ANALYSIS_PROMPT_FILE = PROMPT_DIR / "market_research_ko.txt"
SENT_NEWS_MAX_IDS = int(os.environ.get("SENT_NEWS_MAX_IDS", "0"))
SENT_NEWS_RETENTION_DAYS = int(os.environ.get("SENT_NEWS_RETENTION_DAYS", "7"))
TELEGRAM_MESSAGE_LIMIT = 4096
NEWS_GLOBAL_LIMIT = int(os.environ.get("NEWS_GLOBAL_LIMIT", "3"))
NEWS_STOCK_LIMIT_PER_SYMBOL = int(os.environ.get("NEWS_STOCK_LIMIT_PER_SYMBOL", "3"))
# 한 주기에 처리할 관심종목 수. 0 이하면 전체를 한 번에 처리(기존 동작).
# 전체 종목을 매 주기 일괄 요청/번역하지 않고 여러 주기에 나눠 회전 처리해 부하를 분산한다.
STOCK_NEWS_BATCH_SIZE = int(os.environ.get("STOCK_NEWS_BATCH_SIZE", "3"))
# 배치 내 종목 간 외부 API 호출 사이에 둘 지연(초). 0이면 지연 없음.
STOCK_NEWS_FETCH_DELAY_SECONDS = float(os.environ.get("STOCK_NEWS_FETCH_DELAY_SECONDS", "0"))
# 한 주기에 처리할 전역 속보 소스(CLS/Futu) 수. 1이면 매 주기 한 소스씩 번갈아 처리.
# 0 이하이면 매 주기 전체(CLS+Futu)를 처리(기존 동작).
GLOBAL_NEWS_BATCH_SIZE = int(os.environ.get("GLOBAL_NEWS_BATCH_SIZE", "1"))
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "5"))
TRANSLATION_CONCURRENCY = int(os.environ.get("TRANSLATION_CONCURRENCY", "2"))
STOCK_DB_ENABLED = os.environ.get("STOCK_DB_ENABLED", "true").lower() == "true"
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
HELP_TEXT = (
    "<b>사용 가능한 명령어</b>\n\n"
    "/start — 봇 소개와 사용 가능한 경로 보기\n"
    "/menu — 관심종목 관리 (삭제)\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/list — 관심종목 목록 확인\n"
    "/research show — 저장된 리서치 주제 보기\n"
    "/research set 리서치주제 — 리서치 주제 저장\n"
    "/research run — 최근 뉴스 기준 리서치 실행\n"
    "/research clear — 리서치 주제 삭제\n"
    "/stockdb build — 종목 코드·이름 목록 갱신\n"
    "/stockdb enrich — EODHD로 시총·업종 보강\n"
    "/system — 시스템 상태 보기\n"
    "/system gpu on|off — Ollama GPU 가속 켜기/끄기\n"
    "/system gpu 레이어수 — GPU 오프로딩 레이어 수 지정\n"
    "/help — 도움말\n\n"
    "종목코드 형식:\n"
    "  • A주 상해: 6자리 (예: 600519)\n"
    "  • A주 심천: 6자리 (예: 300750)\n"
    "  • 홍콩: 5자리 (예: 09988)"
)
