import asyncio
import html
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

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
logger = logging.getLogger(__name__)

SENT_IDS_FILE     = BASE_DIR / "data" / "sent_ids.json"
WATCHLIST_FILE    = BASE_DIR / "data" / "watchlist.json"
STOCK_DB_FILE     = BASE_DIR / "data" / "stock_db.json"
PROMPT_DIR        = Path(os.environ.get("TRANSLATE_PROMPT_DIR", "prompts"))
if not PROMPT_DIR.is_absolute():
    PROMPT_DIR = BASE_DIR / PROMPT_DIR
MAX_SENT_IDS      = 1000
TELEGRAM_MESSAGE_LIMIT = 4096
CLS_FUTU_NEWS_LIMIT = int(os.environ.get("CLS_FUTU_NEWS_LIMIT", "10"))
STOCK_NEWS_LIMIT = int(os.environ.get("STOCK_NEWS_LIMIT", "5"))
SCHEDULE_INTERVAL_MINUTES = int(os.environ.get("SCHEDULE_INTERVAL_MINUTES", "3"))
TRANSLATE_CONCURRENCY = int(os.environ.get("TRANSLATE_CONCURRENCY", "2"))
STOCK_DB_ENABLED = os.environ.get("STOCK_DB_ENABLED", "true").lower() == "true"
DEFAULT_WATCHLIST: Dict[str, str] = {
    "09988":  "알리바바",
    "300750": "CATL",
}

HELP_TEXT = (
    "📖 <b>사용 가능한 명령어</b>\n\n"
    "/menu — 관심종목 관리 (삭제)\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/list — 관심종목 목록 확인\n"
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
            self._file_path.write_text(
                json.dumps(self._watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            self._watchlist = json.loads(self._file_path.read_text(encoding="utf-8"))

    async def _persist(self):
        data = json.dumps(self._watchlist, ensure_ascii=False, indent=2)
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

    # StockDB 우선 조회 (A주/홍콩 전 종목 포함)
    name = stock_db.get_cn_name(code)
    if name:
        await wm.add(code, name)
        await update.message.reply_text(f"✅ 추가됨: {name} ({code})\n/menu 로 목록 확인")
        logger.info("[WATCHLIST] 추가 (DB): %s %s", code, name)
        return

    await update.message.reply_text(f"🔍 {code} 종목명 조회 중...")
    try:
        name = await asyncio.to_thread(_resolve_stock_name, code)
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


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    wm: WatchlistManager = context.bot_data["watchlist_manager"]
    data = query.data

    if data == "close":
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
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_db"]             = stock_db
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
    )
    app.bot_data["translate_semaphore"]  = asyncio.Semaphore(TRANSLATE_CONCURRENCY)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CommandHandler("add",   cmd_add))
    app.add_handler(CommandHandler("list",  cmd_list))
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
    logger.info("명령어: /start /help /menu /add /list")
    app.run_polling()


if __name__ == "__main__":
    main()
