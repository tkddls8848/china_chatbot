import asyncio
import html
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import akshare as ak
import pandas as pd
import requests.exceptions
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from market_view import MarketViewAnalyzer, MarketViewError, MarketViewManager
from stock_db import StockDatabase
from translator import TranslationService

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

SENT_IDS_FILE     = BASE_DIR / "data" / "sent_ids.json"
WATCHLIST_FILE    = BASE_DIR / "data" / "watchlist.json"
STOCK_DB_FILE     = BASE_DIR / "data" / "stock_db.json"
MARKET_VIEW_FILE  = BASE_DIR / "data" / "market_view.json"
PROMPT_DIR        = Path(os.environ.get("TRANSLATE_PROMPT_DIR", "prompts"))
if not PROMPT_DIR.is_absolute():
    PROMPT_DIR = BASE_DIR / PROMPT_DIR
MARKET_VIEW_PROMPT_FILE = PROMPT_DIR / "market_view_ko.txt"
MAX_SENT_IDS      = 1000
TELEGRAM_MESSAGE_LIMIT = 4096
CLS_FUTU_NEWS_LIMIT = int(os.environ.get("CLS_FUTU_NEWS_LIMIT", "10"))
STOCK_NEWS_LIMIT = int(os.environ.get("STOCK_NEWS_LIMIT", "5"))
SCHEDULE_INTERVAL_MINUTES = int(os.environ.get("SCHEDULE_INTERVAL_MINUTES", "3"))
TRANSLATE_CONCURRENCY = int(os.environ.get("TRANSLATE_CONCURRENCY", "2"))
STOCK_DB_ENABLED = os.environ.get("STOCK_DB_ENABLED", "true").lower() == "true"
VIEW_MAX_CHANGES = int(os.environ.get("VIEW_MAX_CHANGES", "5"))
VIEW_MAX_ADD = int(os.environ.get("VIEW_MAX_ADD", "5"))
VIEW_MAX_REMOVE = int(os.environ.get("VIEW_MAX_REMOVE", "3"))
VIEW_PENDING_TTL_MINUTES = int(os.environ.get("VIEW_PENDING_TTL_MINUTES", "10"))
VIEW_NEWS_LIMIT_PER_STOCK = int(os.environ.get("VIEW_NEWS_LIMIT_PER_STOCK", "2"))
VIEW_MAX_NEWS_ITEMS = int(os.environ.get("VIEW_MAX_NEWS_ITEMS", "20"))
VIEW_GLOBAL_NEWS_LIMIT = int(os.environ.get("VIEW_GLOBAL_NEWS_LIMIT", "20"))
VIEW_MAX_CANDIDATES = int(os.environ.get("VIEW_MAX_CANDIDATES", "60"))
VIEW_KEYWORD_CANDIDATES_LIMIT = int(os.environ.get("VIEW_KEYWORD_CANDIDATES_LIMIT", "20"))
MARKET_VIEW_NUM_PREDICT = int(os.environ.get("MARKET_VIEW_NUM_PREDICT", "2048"))

# 한국어/영어 키워드 → 중국어 종목명 부분문자열 매핑
_VIEW_KEYWORD_MAP: dict[str, list[str]] = {
    "ai":       ["人工智能", "智能", "大模型", "算力"],
    "인공지능": ["人工智能", "智能", "大模型"],
    "llm":      ["大模型", "人工智能"],
    "반도체":   ["半导体", "芯片", "集成电路", "晶圆"],
    "칩":       ["芯片", "半导体"],
    "전기차":   ["新能源", "电动", "汽车"],
    "ev":       ["新能源", "电动"],
    "배터리":   ["电池", "储能", "锂"],
    "태양광":   ["光伏", "太阳能"],
    "신재생":   ["光伏", "风电", "新能源"],
    "풍력":     ["风电", "风能"],
    "로봇":     ["机器人", "自动化"],
    "클라우드": ["云计算", "云服务"],
    "5g":       ["通信", "5G"],
    "통신":     ["通信", "电信"],
    "바이오":   ["生物", "基因"],
    "제약":     ["医药", "药业", "制药"],
    "헬스케어": ["医疗", "医药", "健康"],
    "소비재":   ["消费", "零售"],
    "부동산":   ["地产", "房地产"],
    "금융":     ["金融", "银行", "证券"],
    "은행":     ["银行"],
    "증권":     ["证券"],
    "에너지":   ["能源", "电力"],
    "원유":     ["石油", "能源"],
    "방산":     ["军工", "航空"],
    "인터넷":   ["互联网", "网络"],
    "플랫폼":   ["互联网", "平台"],
    "게임":     ["游戏"],
    "장비":     ["设备", "仪器"],
}
DEFAULT_WATCHLIST: Dict[str, str] = {
    "09988":  "알리바바",
    "300750": "CATL",
}

HELP_TEXT = (
    "📖 <b>사용 가능한 명령어</b>\n\n"
    "/menu — 관심종목 관리 (삭제)\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/list — 관심종목 목록 확인\n"
    "/view show — 저장된 시장 뷰 보기\n"
    "/help — 도움말\n\n"
    "종목코드 형식:\n"
    "  • A주 상해: 6자리 (예: 600519)\n"
    "  • A주 심천: 6자리 (예: 300750)\n"
    "  • 홍콩: 5자리 (예: 09988)"
)


# ── 상태 관리 클래스 ──────────────────────────────────

class SentNewsTracker:
    """중복 전송 방지 (최대 MAX_SENT_IDS건 유지, 초과 시 오래된 것 제거)"""

    def __init__(self, file_path: Path, max_size: int = MAX_SENT_IDS):
        self._file_path = file_path
        self._max_size  = max_size
        self._ids: list[str] = []
        self._id_set: set[str] = set()
        self._pending: set[str] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if self._file_path.exists():
            self._ids    = json.loads(self._file_path.read_text(encoding="utf-8"))
            self._id_set = set(self._ids)

    async def reserve(self, article_id: str) -> bool:
        """처리 중이거나 이미 보낸 ID가 아니면 pending으로 예약한다."""
        async with self._lock:
            if article_id in self._id_set or article_id in self._pending:
                return False
            self._pending.add(article_id)
            return True

    async def confirm(self, article_id: str) -> None:
        """텔레그램 전송 성공 후 sent 목록에 확정한다."""
        async with self._lock:
            self._pending.discard(article_id)
            if article_id in self._id_set:
                return
            self._ids.append(article_id)
            self._id_set.add(article_id)
            if len(self._ids) > self._max_size:
                oldest = self._ids.pop(0)
                self._id_set.discard(oldest)

    async def release(self, article_id: str) -> None:
        """번역 또는 전송 실패 시 다음 주기에 재시도할 수 있도록 예약을 해제한다."""
        async with self._lock:
            self._pending.discard(article_id)

    async def persist(self):
        async with self._lock:
            data = json.dumps(self._ids, ensure_ascii=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")


class WatchlistManager:
    """관심종목 관리"""

    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._watchlist: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not self._file_path.exists():
            self._watchlist = DEFAULT_WATCHLIST.copy()
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(self._watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            self._watchlist = json.loads(self._file_path.read_text(encoding="utf-8"))

    async def _persist(self):
        data = json.dumps(self._watchlist, ensure_ascii=False, indent=2)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")

    async def get_all(self) -> Dict[str, str]:
        async with self._lock:
            return self._watchlist.copy()

    async def add(self, code: str, name: str) -> None:
        async with self._lock:
            self._watchlist[code] = name
            await self._persist()

    async def remove(self, code: str) -> Optional[str]:
        async with self._lock:
            name = self._watchlist.pop(code, None)
            if name is not None:
                await self._persist()
            return name


# ── akshare 재시도 (네트워크 오류만) ─────────────────

def retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )(func)


@retry_on_network
def _fetch_cls_raw():
    return ak.stock_info_global_cls()


@retry_on_network
def _fetch_futu_raw():
    return ak.stock_info_global_futu()


@retry_on_network
def _fetch_stock_news_raw(symbol: str):
    return ak.stock_news_em(symbol=symbol)


# ── 종목명 자동 조회 ──────────────────────────────────

def _resolve_stock_name(code: str) -> str:
    if len(code) <= 5:
        df   = ak.stock_individual_basic_info_hk_xq(symbol=code)
        name = df[df["item"] == "comcnname"]["value"].values[0]
    elif code.startswith(("00", "30")):
        df   = ak.stock_individual_basic_info_xq(symbol=f"SZ{code}")
        name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
    elif code.startswith(("60", "68")):
        df   = ak.stock_individual_basic_info_xq(symbol=f"SH{code}")
        name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
    else:
        raise ValueError(f"알 수 없는 종목코드 형식: {code}")
    return str(name)


def _build_news_message(
    header: str,
    title: str,
    content: str,
    footer: str = "",
    related_stocks: list[tuple[str, str]] | None = None,
) -> str:
    truncation = "..."
    safe_title = html.escape(title)
    raw_content = content

    if related_stocks:
        items = ", ".join(f"{code}({html.escape(name)})" for code, name in related_stocks)
        related_line = f"\n\n🔖 관련종목 : {items}"
    else:
        related_line = ""

    while True:
        safe_content = html.escape(raw_content)
        title_part = f"<b>{safe_title}</b>\n\n" if safe_title else ""
        text = f"{header}{title_part}{safe_content}{related_line}{footer}"
        if len(text) <= TELEGRAM_MESSAGE_LIMIT:
            return text

        overflow = len(text) - TELEGRAM_MESSAGE_LIMIT
        keep = max(0, len(raw_content) - overflow - len(truncation) - 20)
        next_content = raw_content[:keep].rstrip() + truncation
        if next_content == raw_content:
            safe_content = ""
            text = f"{header}{title_part}{related_line}{footer}"
            return text[: TELEGRAM_MESSAGE_LIMIT - len(truncation)] + truncation
        raw_content = next_content


async def _translate_article(
    translator: TranslationService,
    semaphore: asyncio.Semaphore,
    source: str,
    title: str,
    content: str,
) -> tuple[str, str, list[str]]:
    async with semaphore:
        return await asyncio.to_thread(
            translator.translate_article,
            source,
            title,
            content,
        )


# ── 뉴스 수집 함수 ────────────────────────────────────

async def fetch_cls(
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    chat_id: str,
    stock_db: StockDatabase,
) -> None:
    try:
        df = await asyncio.to_thread(_fetch_cls_raw)
    except Exception as e:
        logger.error("[CLS] API 호출 실패: %s", e)
        return

    async def prepare_row(row):
        article_id = str(row["发布日期"]) + " " + str(row["发布时间"]) + str(row["标题"])
        try:
            if not await tracker.reserve(article_id):
                return None
            raw_title = str(row["标题"])
            raw_content = str(row["内容"])
            title, content, related_codes = await _translate_article(
                translator,
                translate_semaphore,
                "cls",
                raw_title,
                raw_content,
            )
            related_stocks = [
                (code, name)
                for code in related_codes
                if (name := stock_db.get_cn_name(code))
            ]
            text = _build_news_message(
                header=(
                    f"📰 <b>財联社 속보</b>\n"
                    f"🕐 {row['发布日期']} {row['发布时间']}\n\n"
                ),
                title=title,
                content=content,
                related_stocks=related_stocks,
            )
            return article_id, text, title
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[CLS] 번역 실패: %s", e)
            return None

    prepared_rows = await asyncio.gather(
        *(prepare_row(row) for _, row in df.tail(CLS_FUTU_NEWS_LIMIT).iterrows())
    )

    for prepared in prepared_rows:
        if prepared is None:
            continue
        article_id, text, title = prepared
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
            )
            await tracker.confirm(article_id)
            logger.info("[CLS] 전송 완료: %s", title[:30])
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[CLS] 전송 실패: %s", e)


async def fetch_futu(
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    chat_id: str,
    stock_db: StockDatabase,
) -> None:
    try:
        df = await asyncio.to_thread(_fetch_futu_raw)
    except Exception as e:
        logger.error("[FUTU] API 호출 실패: %s", e)
        return

    async def prepare_row(row):
        article_id = str(row["发布时间"]) + str(row["内容"])[:20]
        try:
            if not await tracker.reserve(article_id):
                return None
            raw_title = str(row["标题"]) if row["标题"] else ""
            raw_content = str(row["内容"])
            title, content, related_codes = await _translate_article(
                translator,
                translate_semaphore,
                "futu",
                raw_title,
                raw_content,
            )
            related_stocks = [
                (code, name)
                for code in related_codes
                if (name := stock_db.get_cn_name(code))
            ]
            link_url = str(row.get("链接") or "")
            link_part = (
                f'\n🔗 <a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                if link_url else ""
            )
            text = _build_news_message(
                header=(
                    f"🐂 <b>富途牛牛 속보</b>\n"
                    f"🕐 {row['发布时间']}\n\n"
                ),
                title=title,
                content=content,
                footer=link_part,
                related_stocks=related_stocks,
            )
            return article_id, text, content
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[FUTU] 번역 실패: %s", e)
            return None

    prepared_rows = await asyncio.gather(
        *(prepare_row(row) for _, row in df.head(CLS_FUTU_NEWS_LIMIT).iloc[::-1].iterrows())
    )

    for prepared in prepared_rows:
        if prepared is None:
            continue
        article_id, text, content = prepared
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
            )
            await tracker.confirm(article_id)
            logger.info("[FUTU] 전송 완료: %s", content[:30])
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[FUTU] 전송 실패: %s", e)


async def fetch_stock_news(
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    wm: WatchlistManager,
    chat_id: str,
    bot_data: dict,
    stock_db: StockDatabase,
) -> None:
    watchlist = await wm.get_all()
    if not watchlist:
        return

    if bot_data.get("stock_news_first_run", True):
        stock_list = "\n".join(
            f"  • {name} ({code})" for code, name in watchlist.items()
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "📌 <b>관심종목 뉴스 조회 시작</b>\n"
                    "➕ 추가: /add 종목코드\n"
                    "➖ 삭제: /menu 에서 버튼으로\n"
                    "📋 목록: /list\n\n"
                    f"{stock_list}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("첫 실행 안내 전송 실패: %s", e)
        bot_data["stock_news_first_run"] = False

    for code, name in watchlist.items():
        try:
            df = await asyncio.to_thread(_fetch_stock_news_raw, code)
            if df.empty:
                continue

            cutoff = datetime.now() - timedelta(days=14)
            df = df[pd.to_datetime(df["发布时间"], errors="coerce") >= cutoff]
            if df.empty:
                continue

            async def prepare_row(row):
                article_id = str(row["发布时间"]) + str(row["新闻标题"])[:20]
                try:
                    if not await tracker.reserve(article_id):
                        return None
                    raw_title = str(row["新闻标题"])
                    raw_content = str(row["新闻内容"])
                    title, content, related_codes = await _translate_article(
                        translator,
                        translate_semaphore,
                        "stock",
                        raw_title,
                        raw_content,
                    )
                    related_stocks = [
                        (rc, rn)
                        for rc in related_codes
                        if (rn := stock_db.get_cn_name(rc))
                    ]
                    source = html.escape(str(row["文章来源"]))
                    link_url = str(row["新闻链接"])
                    link = f'<a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                    text = _build_news_message(
                        header=(
                            f"🏢 <b>{html.escape(name)} ({code}) 뉴스</b>\n"
                            f"🕐 {row['发布时间']}\n"
                            f"📌 {source}\n\n"
                        ),
                        title=title,
                        content=content,
                        footer=f"\n\n🔗 {link}",
                        related_stocks=related_stocks,
                    )
                    return article_id, text, title
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 번역 실패: %s", name, e)
                    return None

            prepared_rows = await asyncio.gather(
                *(prepare_row(row) for _, row in df.head(STOCK_NEWS_LIMIT).iterrows())
            )

            for prepared in prepared_rows:
                if prepared is None:
                    continue
                article_id, text, title = prepared
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                    )
                    await tracker.confirm(article_id)
                    logger.info("[STOCK] 전송 완료: %s %s", name, title[:20])
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 전송 실패: %s", name, e)
        except Exception as e:
            logger.error("[STOCK] %s 오류: %s", name, e)


def _row_value(row, candidates: list[str], fallback_index: int | None = None) -> str:
    for key in candidates:
        if key in row.index:
            value = row[key]
            return "" if pd.isna(value) else str(value)
    if fallback_index is not None and fallback_index < len(row.index):
        value = row.iloc[fallback_index]
        return "" if pd.isna(value) else str(value)
    return ""


async def collect_watchlist_news_items(
    watchlist: Dict[str, str],
    limit_per_stock: int = VIEW_NEWS_LIMIT_PER_STOCK,
) -> list[dict[str, str]]:
    news_items: list[dict[str, str]] = []
    cutoff = datetime.now() - timedelta(days=14)

    for code, name in watchlist.items():
        try:
            df = await asyncio.to_thread(_fetch_stock_news_raw, code)
            if df.empty:
                continue

            published_raw = (
                df["发布时间"]
                if "发布时间" in df.columns
                else df.iloc[:, 3]
            )
            published_series = pd.to_datetime(published_raw, errors="coerce")
            df = df[published_series >= cutoff]
            if df.empty:
                continue

            for _, row in df.head(limit_per_stock).iterrows():
                published_at = _row_value(row, ["发布时间"], 3)
                title = _row_value(row, ["新闻标题"], 1)
                content = _row_value(row, ["新闻内容"], 2)
                source = _row_value(row, ["文章来源"], 4) or "Stock"
                url = _row_value(row, ["新闻链接"], 5)
                if not title and not content:
                    continue
                news_items.append(
                    {
                        "id": f"stock:{code}:{published_at}:{title[:20]}",
                        "source": source,
                        "ticker": code,
                        "name": name,
                        "title": title,
                        "content": content[:700],
                        "published_at": published_at,
                        "url": url,
                    }
                )
                if len(news_items) >= VIEW_MAX_NEWS_ITEMS:
                    return news_items
        except Exception as e:
            logger.error("[VIEW] %s news collection failed: %s", name, e)

    return news_items


def _make_news_item(
    source: str,
    title: str,
    content: str,
    published_at: str,
    url: str = "",
) -> dict[str, str]:
    return {
        "id": f"{source}:{published_at}:{title[:30]}",
        "source": source,
        "ticker": "",
        "name": "",
        "title": title,
        "content": content[:700],
        "published_at": published_at,
        "url": url,
    }


async def collect_global_market_news_items() -> list[dict[str, str]]:
    news_items: list[dict[str, str]] = []

    try:
        df_cls = await asyncio.to_thread(_fetch_cls_raw)
        for _, row in df_cls.tail(VIEW_GLOBAL_NEWS_LIMIT).iterrows():
            published_date = _row_value(row, ["发布日期", "?묈툋?ζ쐿"], 0)
            published_time = _row_value(row, ["发布时间", "?묈툋?띌뿴"], 1)
            title = _row_value(row, ["标题", "?뉔쥦"], 2)
            content = _row_value(row, ["内容", "?끻?"], 3)
            if title or content:
                news_items.append(
                    _make_news_item(
                        "CLS",
                        title,
                        content,
                        f"{published_date} {published_time}".strip(),
                    )
                )
            if len(news_items) >= VIEW_MAX_NEWS_ITEMS:
                return news_items
    except Exception as e:
        logger.error("[VIEW] CLS news collection failed: %s", e)

    try:
        df_futu = await asyncio.to_thread(_fetch_futu_raw)
        for _, row in df_futu.head(VIEW_GLOBAL_NEWS_LIMIT).iterrows():
            title = _row_value(row, ["标题", "?뉔쥦"], 0)
            content = _row_value(row, ["内容", "?끻?"], 1)
            published_at = _row_value(row, ["发布时间", "?묈툋?띌뿴"], 2)
            url = _row_value(row, ["链接", "?얏렏"], 3)
            if title or content:
                news_items.append(
                    _make_news_item("Futu", title, content, published_at, url)
                )
            if len(news_items) >= VIEW_MAX_NEWS_ITEMS:
                return news_items
    except Exception as e:
        logger.error("[VIEW] Futu news collection failed: %s", e)

    return news_items


def _name_is_matchable(name: str) -> bool:
    name = name.strip()
    if len(name) >= 3:
        return True
    return len(name) >= 4 and name.isascii()


def _extract_view_cn_patterns(market_view: str) -> list[str]:
    """market_view 텍스트에서 중국어 종목명 검색 패턴 추출"""
    view_lower = market_view.lower()
    patterns: list[str] = []
    for keyword, cn_list in _VIEW_KEYWORD_MAP.items():
        if keyword in view_lower:
            patterns.extend(cn_list)
    return list(dict.fromkeys(patterns))  # 순서 유지 dedup


def build_view_candidate_universe(
    stock_db: StockDatabase,
    watchlist: Dict[str, str],
    news_items: list[dict[str, str]],
    market_view: str = "",
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    haystacks = [
        f"{item.get('title', '')}\n{item.get('content', '')}"
        for item in news_items
    ]

    # 1. 워치리스트 (항상 포함)
    for code, name in watchlist.items():
        candidates[code] = {
            "code": code,
            "name": name,
            "market": "",
            "in_watchlist": True,
            "matched_news": [],
        }

    # 2. 시장 뷰 키워드 매칭 (오늘 뉴스 무관, 테마 기반)
    cn_patterns = _extract_view_cn_patterns(market_view) if market_view else []
    if cn_patterns:
        view_added = 0
        for entry in stock_db.get_candidate_universe():
            if view_added >= VIEW_KEYWORD_CANDIDATES_LIMIT:
                break
            code = str(entry.get("code") or "")
            name = str(entry.get("name") or "").strip()
            if not code or not name or code in candidates:
                continue
            if any(pat in name for pat in cn_patterns):
                candidates[code] = {
                    "code": code,
                    "name": name,
                    "market": entry.get("market", ""),
                    "in_watchlist": False,
                    "matched_news": [],
                }
                view_added += 1
        logger.info("[VIEW] 키워드 후보 %d개 추가 (패턴: %s)", view_added, cn_patterns[:5])

    # 3. 뉴스 본문 종목명 매칭 (기존 로직)
    for entry in stock_db.get_candidate_universe():
        code = str(entry.get("code") or "")
        name = str(entry.get("name") or "").strip()
        if not code or not name or not _name_is_matchable(name):
            continue

        matched_news = []
        for item, haystack in zip(news_items, haystacks):
            if name in haystack:
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
        if len(candidates) >= VIEW_MAX_CANDIDATES:
            break

    return list(candidates.values())[:VIEW_MAX_CANDIDATES]


async def _refresh_stock_db(stock_db: StockDatabase) -> None:
    try:
        await asyncio.to_thread(stock_db.build)
        logger.info("[StockDB] 일별 갱신 완료")
    except Exception as e:
        logger.warning("[StockDB] 일별 갱신 실패: %s", e)


async def fetch_all(app: Application) -> None:
    tracker: SentNewsTracker = app.bot_data["sent_tracker"]
    wm: WatchlistManager     = app.bot_data["watchlist_manager"]
    translator: TranslationService = app.bot_data["translator"]
    translate_semaphore: asyncio.Semaphore = app.bot_data["translate_semaphore"]
    stock_db: StockDatabase = app.bot_data["stock_db"]
    await fetch_cls(app.bot, tracker, translator, translate_semaphore, CHAT_ID, stock_db)
    await fetch_futu(app.bot, tracker, translator, translate_semaphore, CHAT_ID, stock_db)
    await fetch_stock_news(
        app.bot,
        tracker,
        translator,
        translate_semaphore,
        wm,
        CHAT_ID,
        app.bot_data,
        stock_db,
    )
    await tracker.persist()


# ── 인라인 키보드 ─────────────────────────────────────

def build_list_keyboard(watchlist: Dict[str, str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {name} ({code})",
            callback_data=f"remove:{code}",
        )]
        for code, name in watchlist.items()
    ]
    buttons.append([InlineKeyboardButton("➕ 종목 추가 방법", callback_data="add_help")])
    buttons.append([InlineKeyboardButton("❌ 닫기", callback_data="close")])
    return InlineKeyboardMarkup(buttons)


def build_view_result_keyboard(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("적용", callback_data=f"view_apply:{uid}"),
                InlineKeyboardButton("취소", callback_data=f"view_cancel:{uid}"),
            ]
        ]
    )


def _normalize_code(code: str) -> str:
    value = "".join(ch for ch in str(code).strip() if ch.isdigit())
    if len(value) <= 5:
        return value.zfill(5)
    return value.zfill(6)


def _pending_expired(created_at: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    return datetime.now() - created > timedelta(minutes=VIEW_PENDING_TTL_MINUTES)


def _prune_expired_view_pending(bot_data: dict) -> None:
    pending = bot_data.setdefault("view_pending", {})
    expired = [
        uid for uid, item in pending.items()
        if _pending_expired(str(item.get("created_at", "")))
    ]
    for uid in expired:
        pending.pop(uid, None)


def _validate_view_actions(
    result: dict[str, Any],
    watchlist: Dict[str, str],
    stock_db: StockDatabase,
    candidate_universe: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    add_items: list[dict[str, Any]] = []
    remove_items: list[dict[str, Any]] = []
    seen_add: set[str] = set()
    seen_remove: set[str] = set()
    allowed_add_codes = {
        str(item.get("code") or "")
        for item in candidate_universe or []
        if not item.get("in_watchlist")
    }

    for item in result.get("actions", []):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"add", "remove"}:
            continue
        evidence = item.get("evidence") or []
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        code = _normalize_code(str(item.get("ticker") or ""))
        if not code:
            continue

        if action == "add":
            if confidence < 0.5:
                continue
            if code not in allowed_add_codes:
                continue
            if code in watchlist or code in seen_add or len(add_items) >= VIEW_MAX_ADD:
                continue
            db_name = stock_db.get_cn_name(code)
            if not db_name:
                continue
            add_items.append(
                {
                    "code": code,
                    "name": db_name,
                    "reason": str(item.get("reason") or "").strip(),
                    "confidence": confidence,
                }
            )
            seen_add.add(code)
        elif action == "remove":
            if not evidence or confidence < 0.5:
                continue
            if code not in watchlist or code in seen_remove or len(remove_items) >= VIEW_MAX_REMOVE:
                continue
            remove_items.append(
                {
                    "code": code,
                    "name": watchlist[code],
                    "reason": str(item.get("reason") or "").strip(),
                    "confidence": confidence,
                }
            )
            seen_remove.add(code)

        if len(add_items) + len(remove_items) >= VIEW_MAX_CHANGES:
            break

    return {"add": add_items, "remove": remove_items}


def _format_action_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        reason = html.escape(str(item.get("reason") or ""))
        code = html.escape(str(item["code"]))
        name = html.escape(str(item["name"]))
        confidence = float(item.get("confidence") or 0)
        suffix = f" - {reason}" if reason else ""
        lines.append(f"- {name} ({code}) [{confidence:.0%}]{suffix}")
    return "\n".join(lines) if lines else "- 없음"


def _format_view_result_message(
    result: dict[str, Any],
    pending: dict[str, list[dict[str, Any]]],
    news_count: int,
    candidate_count: int = 0,
    temporary: bool = False,
) -> str:
    title = "시장 뷰 분석 결과"
    if temporary:
        title += " (임시 뷰)"

    summary = html.escape(result.get("summary") or "요약 없음")
    add_lines = _format_action_lines(pending["add"])
    remove_lines = _format_action_lines(pending["remove"])

    watch_lines = []
    keep_lines = []
    for item in result.get("actions", []):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"watch", "keep"}:
            continue
        code = html.escape(_normalize_code(str(item.get("ticker") or "")))
        name = html.escape(str(item.get("name") or code))
        reason = html.escape(str(item.get("reason") or ""))
        line = f"- {name} ({code})"
        if reason:
            line += f" - {reason}"
        if action == "watch":
            watch_lines.append(line)
        else:
            keep_lines.append(line)

    risks = result.get("risks") or []
    risk_lines = "\n".join(f"- {html.escape(str(r))}" for r in risks[:5]) or "- 없음"
    text = (
        f"<b>{html.escape(title)}</b>\n"
        f"분석 뉴스: {news_count}건 / 후보 universe: {candidate_count}개\n\n"
        f"<b>요약</b>\n{summary}\n\n"
        f"<b>추가 후보</b>\n{add_lines}\n\n"
        f"<b>제외 후보</b>\n{remove_lines}\n\n"
        f"<b>주목 종목</b>\n{chr(10).join(watch_lines[:5]) or '- 없음'}\n\n"
        f"<b>유지</b>\n{chr(10).join(keep_lines[:5]) or '- 없음'}\n\n"
        f"<b>리스크</b>\n{risk_lines}"
    )
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."
    return text


# ── 명령어 핸들러 ─────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    watchlist = await wm.get_all()
    if not watchlist:
        await update.message.reply_text(
            "📭 관심종목이 없습니다.\n/add 종목코드 로 추가하세요."
        )
        return
    await update.message.reply_text(
        "📋 <b>관심종목 관리</b>\n종목 버튼을 누르면 삭제됩니다.",
        parse_mode="HTML",
        reply_markup=build_list_keyboard(watchlist),
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    stock_db: StockDatabase = context.bot_data["stock_db"]
    if len(context.args) < 1:
        await update.message.reply_text(
            "사용법: /add 종목코드\n"
            "예: /add 300750"
        )
        return

    code = context.args[0].strip()

    if len(context.args) >= 2:
        await update.message.reply_text(
            f"종목코드만 입력하세요.\n사용법: /add {code}"
        )
        return

    translator: TranslationService = context.bot_data["translator"]

    # StockDB 우선 조회 (A주/홍콩 전 종목 포함)
    cn_name = stock_db.get_cn_name(code)
    if cn_name:
        name = await asyncio.to_thread(translator.translate_stock_name, cn_name)
        await wm.add(code, name)
        await update.message.reply_text(f"✅ 추가됨: {name} ({code})\n/menu 로 목록 확인")
        logger.info("[WATCHLIST] 추가 (DB): %s %s", code, name)
        return

    await update.message.reply_text(f"🔍 {code} 종목명 조회 중...")
    try:
        cn_name = await asyncio.to_thread(_resolve_stock_name, code)
        name = await asyncio.to_thread(translator.translate_stock_name, cn_name)
        await wm.add(code, name)
        await update.message.reply_text(f"✅ 추가됨: {name} ({code})\n/menu 로 목록 확인")
        logger.info("[WATCHLIST] 추가 (API): %s %s", code, name)
    except Exception as e:
        logger.error("[WATCHLIST] 종목명 조회 실패: %s %s", code, e)
        await update.message.reply_text(
            f"❌ {code} 종목명 자동 조회 실패\n"
            "종목코드를 확인한 뒤 다시 시도하세요."
        )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    watchlist = await wm.get_all()
    if not watchlist:
        await update.message.reply_text("📭 관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    stock_list = "\n".join(f"  • {name} ({code})" for code, name in watchlist.items())
    await update.message.reply_text(
        f"📋 <b>현재 관심종목</b>\n\n{stock_list}",
        parse_mode="HTML",
        reply_markup=build_list_keyboard(watchlist),
    )


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await _handle_view_show(update, context)
        return

    command = args[0].lower()
    if command == "show":
        await _handle_view_show(update, context)
    elif command == "set":
        await _handle_view_set(update, context, " ".join(args[1:]).strip())
    elif command == "run":
        mvm: MarketViewManager = context.bot_data["market_view_manager"]
        market_view = mvm.get_view()
        if not market_view:
            await update.message.reply_text(
                "저장된 시장 뷰가 없습니다.\n/view set 시장뷰내용 으로 먼저 저장하세요."
            )
            return
        await _handle_view_run(update, context, market_view)
    elif command == "clear":
        await _handle_view_clear(update, context)
    else:
        await _handle_view_run(update, context, " ".join(args).strip(), temporary=True)


async def _handle_view_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    view = mvm.get_view()
    last_result = mvm.get_last_result()

    if view:
        view_text = html.escape(view)
    else:
        view_text = "저장된 시장 뷰 없음"

    if last_result:
        generated_at = html.escape(str(last_result.get("generated_at") or ""))
        summary = html.escape(str(last_result.get("summary") or "요약 없음"))
        last_text = f"- 마지막 실행: {generated_at}\n- 요약: {summary}"
    else:
        last_text = "- 최근 분석 없음"

    await update.message.reply_text(
        "<b>시장 뷰</b>\n"
        f"{view_text}\n\n"
        "<b>최근 분석</b>\n"
        f"{last_text}\n\n"
        "<b>명령</b>\n"
        "/view show\n"
        "/view set 시장뷰내용\n"
        "/view run\n"
        "/view clear",
        parse_mode="HTML",
    )


async def _handle_view_set(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
) -> None:
    if not market_view:
        await update.message.reply_text("사용법: /view set 시장뷰내용")
        return

    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    await asyncio.to_thread(mvm.set_view, market_view)
    await update.message.reply_text(
        "시장 뷰를 저장했습니다.\n/view run 으로 분석을 실행하세요."
    )


async def _handle_view_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    await asyncio.to_thread(mvm.clear_view)
    context.bot_data["view_pending"] = {}
    await update.message.reply_text("시장 뷰를 삭제했습니다. 워치리스트는 변경하지 않았습니다.")


async def _handle_view_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
    temporary: bool = False,
) -> None:
    if not market_view:
        await update.message.reply_text("사용법: /view set 시장뷰내용")
        return

    _prune_expired_view_pending(context.bot_data)
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    stock_db: StockDatabase = context.bot_data["stock_db"]
    analyzer: MarketViewAnalyzer = context.bot_data["market_view_analyzer"]
    mvm: MarketViewManager = context.bot_data["market_view_manager"]

    watchlist = await wm.get_all()
    status_message = await update.message.reply_text("전체 시장 뉴스 기준으로 시장 뷰 분석 중...")
    news_items = await collect_global_market_news_items()
    if not news_items:
        await status_message.edit_text("최근 전체 시장 뉴스가 없어 분석을 실행하지 않았습니다.")
        return
    candidate_universe = build_view_candidate_universe(stock_db, watchlist, news_items, market_view)

    try:
        result = await asyncio.to_thread(
            analyzer.analyze,
            market_view,
            watchlist,
            news_items,
            candidate_universe,
        )
    except MarketViewError as e:
        logger.error("[VIEW] analysis failed: %s", e)
        await status_message.edit_text(f"분석 실패: {html.escape(str(e))}", parse_mode="HTML")
        return
    except Exception as e:
        logger.error("[VIEW] analysis error: %s", e)
        await status_message.edit_text(f"분석 실패: {html.escape(str(e))}", parse_mode="HTML")
        return

    pending = _validate_view_actions(result, watchlist, stock_db, candidate_universe)
    if not temporary:
        await asyncio.to_thread(mvm.save_result, result)

    text = _format_view_result_message(
        result,
        pending,
        len(news_items),
        len(candidate_universe),
        temporary,
    )
    has_changes = bool(pending["add"] or pending["remove"])
    if not has_changes:
        await status_message.edit_text(
            text + "\n\n변경 적용 후보가 없습니다.",
            parse_mode="HTML",
        )
        return

    uid = uuid.uuid4().hex[:8]
    context.bot_data.setdefault("view_pending", {})[uid] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "market_view": market_view,
        "add": pending["add"],
        "remove": pending["remove"],
        "summary": result.get("summary") or "",
    }
    await status_message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=build_view_result_keyboard(uid),
    )


async def _handle_view_apply(query, context: ContextTypes.DEFAULT_TYPE, uid: str) -> None:
    pending_map = context.bot_data.setdefault("view_pending", {})
    pending = pending_map.pop(uid, None)
    if not pending or _pending_expired(str(pending.get("created_at", ""))):
        await query.message.edit_text("만료된 요청입니다. /view run을 다시 실행하세요.")
        return

    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    stock_db: StockDatabase = context.bot_data["stock_db"]
    watchlist = await wm.get_all()
    added: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []

    for item in pending.get("remove", []):
        code = str(item.get("code") or "")
        if code in watchlist:
            name = await wm.remove(code)
            removed.append(f"{name or item.get('name') or code} ({code})")
            watchlist.pop(code, None)
        else:
            skipped.append(f"{item.get('name') or code} ({code})")

    translator: TranslationService = context.bot_data["translator"]
    for item in pending.get("add", []):
        code = str(item.get("code") or "")
        if code in watchlist:
            skipped.append(f"{watchlist[code]} ({code})")
            continue
        db_name = stock_db.get_cn_name(code)
        if not db_name:
            skipped.append(f"{item.get('name') or code} ({code})")
            continue
        name = await asyncio.to_thread(translator.translate_stock_name, db_name)
        await wm.add(code, name)
        added.append(f"{name} ({code})")
        watchlist[code] = name

    text = (
        "<b>시장 뷰 변경 적용 완료</b>\n\n"
        f"<b>추가</b>\n{chr(10).join('- ' + html.escape(x) for x in added) or '- 없음'}\n\n"
        f"<b>삭제</b>\n{chr(10).join('- ' + html.escape(x) for x in removed) or '- 없음'}"
    )
    if skipped:
        text += f"\n\n<b>건너뜀</b>\n{chr(10).join('- ' + html.escape(x) for x in skipped)}"
    await query.message.edit_text(text, parse_mode="HTML")


async def _handle_view_cancel(query, context: ContextTypes.DEFAULT_TYPE, uid: str) -> None:
    context.bot_data.setdefault("view_pending", {}).pop(uid, None)
    await query.message.edit_text("시장 뷰 변경 적용을 취소했습니다.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    data = query.data

    if data.startswith("view_apply:"):
        uid = data.split(":", 1)[1]
        await _handle_view_apply(query, context, uid)

    elif data.startswith("view_cancel:"):
        uid = data.split(":", 1)[1]
        await _handle_view_cancel(query, context, uid)

    elif data == "close":
        await query.message.delete()

    elif data == "add_help":
        await query.message.reply_text(
            "➕ 추가할 종목을 입력하세요.\n\n"
            "형식: /add 종목코드\n"
            "예시: /add 600519"
        )

    elif data.startswith("remove:"):
        code = data.split(":", 1)[1]
        name = await wm.remove(code) or code
        logger.info("[WATCHLIST] 삭제: %s %s", code, name)
        watchlist = await wm.get_all()
        if not watchlist:
            await query.message.edit_text("📭 관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
            return
        await query.message.edit_text(
            f"🗑 <b>{html.escape(name)} ({code}) 삭제됨</b>\n\n"
            "📋 <b>관심종목 관리</b>\n종목 버튼을 누르면 삭제됩니다.",
            parse_mode="HTML",
            reply_markup=build_list_keyboard(watchlist),
        )


# ── 진입점 ────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    stock_db = StockDatabase(cache_file=STOCK_DB_FILE, enabled=STOCK_DB_ENABLED)
    stock_db.load_or_build()

    app.bot_data["sent_tracker"]         = SentNewsTracker(SENT_IDS_FILE)
    app.bot_data["watchlist_manager"]    = WatchlistManager(WATCHLIST_FILE)
    app.bot_data["market_view_manager"]  = MarketViewManager(MARKET_VIEW_FILE)
    app.bot_data["view_pending"]         = {}
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_db"]             = stock_db
    ollama_num_gpu = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
    app.bot_data["translator"]           = TranslationService(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("TRANSLATE_MODEL", "gemma4"),
        enabled=os.environ.get("TRANSLATE_ENABLED", "true").lower() == "true",
        timeout=int(os.environ.get("TRANSLATE_TIMEOUT", "60")),
        prompt_dir=PROMPT_DIR,
        fallback_to_original=(
            os.environ.get("TRANSLATE_FALLBACK_TO_ORIGINAL", "false").lower()
            == "true"
        ),
        num_gpu=ollama_num_gpu,
        num_predict=int(os.environ.get("TRANSLATE_NUM_PREDICT", "768")),
    )
    app.bot_data["market_view_analyzer"] = MarketViewAnalyzer(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("MARKET_VIEW_MODEL", os.environ.get("TRANSLATE_MODEL", "gemma4")),
        enabled=os.environ.get("MARKET_VIEW_ENABLED", "true").lower() == "true",
        timeout=int(os.environ.get("MARKET_VIEW_TIMEOUT", os.environ.get("TRANSLATE_TIMEOUT", "180"))),
        num_predict=MARKET_VIEW_NUM_PREDICT,
        prompt_file=MARKET_VIEW_PROMPT_FILE,
        num_gpu=ollama_num_gpu,
    )
    app.bot_data["translate_semaphore"]  = asyncio.Semaphore(TRANSLATE_CONCURRENCY)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CommandHandler("add",   cmd_add))
    app.add_handler(CommandHandler("list",  cmd_list))
    app.add_handler(CommandHandler("view",  cmd_view))
    app.add_handler(CallbackQueryHandler(callback_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        fetch_all,
        trigger="interval",
        minutes=SCHEDULE_INTERVAL_MINUTES,
        args=[app],
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _refresh_stock_db,
        trigger="cron",
        hour=8,
        minute=30,
        args=[stock_db],
        id="refresh_stock_db",
    )
    scheduler.start()

    logger.info(
        "봇 시작됨. %s분마다 財联社 + 富途牛牛 + 관심종목 뉴스 전송.",
        SCHEDULE_INTERVAL_MINUTES,
    )
    logger.info("명령어: /start /help /menu /add /list /view")
    app.run_polling()


if __name__ == "__main__":
    main()
