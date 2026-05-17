import asyncio
import html
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from news import (
    fetch_cls_raw as _fetch_cls_raw,
    fetch_futu_raw as _fetch_futu_raw,
    fetch_stock_news_raw as _fetch_stock_news_raw,
)
from research import (
    MarketViewAnalyzer,
    MarketViewManager,
    cmd_research,
    handle_research_callback,
)
from state import SentNewsTracker
from stock_db import StockDatabase
from translator import TranslationResult, TranslationService
from watchlist import (
    WatchlistManager,
    cmd_add,
    cmd_list,
    cmd_menu,
    handle_watchlist_callback,
)

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
MAX_SENT_IDS      = int(os.environ.get("MAX_SENT_IDS", "0"))
TELEGRAM_MESSAGE_LIMIT = 4096
CLS_FUTU_NEWS_LIMIT = int(os.environ.get("CLS_FUTU_NEWS_LIMIT", "10"))
STOCK_NEWS_LIMIT = int(os.environ.get("STOCK_NEWS_LIMIT", "5"))
SCHEDULE_INTERVAL_MINUTES = int(os.environ.get("SCHEDULE_INTERVAL_MINUTES", "5"))
TRANSLATE_CONCURRENCY = int(os.environ.get("TRANSLATE_CONCURRENCY", "2"))
STOCK_DB_ENABLED = os.environ.get("STOCK_DB_ENABLED", "true").lower() == "true"
RESEARCH_NEWS_LIMIT_PER_STOCK = int(
    os.environ.get("RESEARCH_NEWS_LIMIT_PER_STOCK", "2")
)
RESEARCH_MAX_NEWS_ITEMS = int(
    os.environ.get("RESEARCH_MAX_NEWS_ITEMS", "20")
)
RESEARCH_GLOBAL_NEWS_LIMIT = int(
    os.environ.get("RESEARCH_GLOBAL_NEWS_LIMIT", "20")
)
MARKET_VIEW_NUM_PREDICT = int(os.environ.get("MARKET_VIEW_NUM_PREDICT", "2048"))
HELP_TEXT = (
    "<b>사용 가능한 명령어</b>\n\n"
    "/menu — 관심종목 관리 (삭제)\n"
    "/add 종목코드 — 관심종목 추가\n"
    "/list — 관심종목 목록 확인\n"
    "/research show — 저장된 리서치 주제 보기\n"
    "/help — 도움말\n\n"
    "종목코드 형식:\n"
    "  • A주 상해: 6자리 (예: 600519)\n"
    "  • A주 심천: 6자리 (예: 300750)\n"
    "  • 홍콩: 5자리 (예: 09988)"
)


def _format_china_time_as_kst(
    published_at: Any,
    published_date: Any | None = None,
) -> str:
    raw_time = str(published_at or "").strip()
    raw_date = str(published_date or "").strip()
    raw = f"{raw_date} {raw_time}".strip() if raw_date else raw_time
    if not raw:
        return "KST"

    try:
        if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", raw):
            fmt = "%H:%M:%S" if raw.count(":") == 2 else "%H:%M"
            converted = datetime.strptime(raw, fmt) + timedelta(hours=1)
            return f"{converted.strftime(fmt)} KST"

        parsed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(parsed):
            return f"{raw} KST"

        converted = parsed.to_pydatetime() + timedelta(hours=1)
        fmt = "%Y-%m-%d %H:%M:%S" if re.search(r":\d{2}:\d{2}", raw) else "%Y-%m-%d %H:%M"
        return f"{converted.strftime(fmt)} KST"
    except Exception:
        return f"{raw} KST"


def _build_news_message(
    header: str,
    title: str,
    content: str,
    footer: str = "",
    mentioned_stocks: list[tuple[str, str]] | None = None,
) -> str:
    truncation = "..."
    safe_title = html.escape(title)
    raw_content = content

    if mentioned_stocks:
        items = ", ".join(f"{code}({html.escape(name)})" for code, name in mentioned_stocks)
        mentioned_line = f"\n\n관련종목: {items}"
    else:
        mentioned_line = ""

    while True:
        safe_content = html.escape(raw_content)
        title_part = f"<b>{safe_title}</b>\n\n" if safe_title else ""
        text = f"{header}{title_part}{safe_content}{mentioned_line}{footer}"
        if len(text) <= TELEGRAM_MESSAGE_LIMIT:
            return text

        overflow = len(text) - TELEGRAM_MESSAGE_LIMIT
        keep = max(0, len(raw_content) - overflow - len(truncation) - 20)
        next_content = raw_content[:keep].rstrip() + truncation
        if next_content == raw_content:
            safe_content = ""
            text = f"{header}{title_part}{mentioned_line}{footer}"
            return text[: TELEGRAM_MESSAGE_LIMIT - len(truncation)] + truncation
        raw_content = next_content


async def _translate_article(
    translator: TranslationService,
    semaphore: asyncio.Semaphore,
    source: str,
    title: str,
    content: str,
) -> TranslationResult:
    async with semaphore:
        return await asyncio.to_thread(
            translator.translate_article,
            source,
            title,
            content,
        )


def _is_timeout_error(error: Exception) -> bool:
    return "timed out" in str(error).lower() or "timeout" in str(error).lower()


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
            translated = await _translate_article(
                translator,
                translate_semaphore,
                "cls",
                raw_title,
                raw_content,
            )
            mentioned_stocks = [
                (code, name)
                for code in translated.mentioned_stocks
                if (name := stock_db.get_cn_name(code))
            ]
            text = _build_news_message(
                header=(
                    f"<b>재련사(財联社) 속보</b>\n"
                    f"시간: {_format_china_time_as_kst(row['发布时间'], row['发布日期'])}\n\n"
                ),
                title=translated.title,
                content=translated.content,
                mentioned_stocks=mentioned_stocks,
            )
            return article_id, text, translated.title
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
            translated = await _translate_article(
                translator,
                translate_semaphore,
                "futu",
                raw_title,
                raw_content,
            )
            mentioned_stocks = [
                (code, name)
                for code in translated.mentioned_stocks
                if (name := stock_db.get_cn_name(code))
            ]
            link_url = str(row.get("链接") or "")
            link_part = (
                f'\n링크: <a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                if link_url else ""
            )
            text = _build_news_message(
                header=(
                    f"<b>푸투니우니우(富途牛牛) 속보</b>\n"
                    f"시간: {_format_china_time_as_kst(row['发布时间'])}\n\n"
                ),
                title=translated.title,
                content=translated.content,
                footer=link_part,
                mentioned_stocks=mentioned_stocks,
            )
            return article_id, text, translated.content
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[FUTU] 번역 실패: %s", e)
            if _is_timeout_error(e):
                raise
            return None

    prepared_rows = []
    for _, row in df.head(CLS_FUTU_NEWS_LIMIT).iloc[::-1].iterrows():
        try:
            prepared_rows.append(await prepare_row(row))
        except Exception:
            logger.error("[FUTU] 타임아웃으로 이번 주기 남은 Futu 번역을 중단합니다.")
            break

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
                    "<b>관심종목 뉴스 조회 시작</b>\n"
                    "추가: /add 종목코드\n"
                    "삭제: /menu 에서 버튼으로\n"
                    "목록: /list\n"
                    "리서치: /research show\n\n"
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
                    translated = await _translate_article(
                        translator,
                        translate_semaphore,
                        "stock",
                        raw_title,
                        raw_content,
                    )
                    source = html.escape(str(row["文章来源"]))
                    link_url = str(row["新闻链接"])
                    link = f'<a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                    text = _build_news_message(
                        header=(
                            f"<b>{html.escape(name)} ({code}) 뉴스</b>\n"
                            f"시간: {_format_china_time_as_kst(row['发布时间'])}\n"
                            f"출처: {source}\n\n"
                        ),
                        title=translated.title,
                        content=translated.content,
                        footer=f"\n\n링크: {link}",
                    )
                    return article_id, text, translated.title
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
    limit_per_stock: int = RESEARCH_NEWS_LIMIT_PER_STOCK,
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
                if len(news_items) >= RESEARCH_MAX_NEWS_ITEMS:
                    return news_items
        except Exception as e:
            logger.error("[RESEARCH] %s news collection failed: %s", name, e)

    return news_items


def _make_news_item(
    source: str,
    title: str,
    content: str,
    published_at: str,
    url: str = "",
    mentioned_stocks: list[str] | None = None,
    theme_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{source}:{published_at}:{title[:30]}",
        "source": source,
        "ticker": "",
        "name": "",
        "title": title,
        "content": content[:700],
        "published_at": published_at,
        "url": url,
        "mentioned_stocks": mentioned_stocks or [],
        "theme_candidates": theme_candidates or [],
    }


async def collect_global_market_news_items(
    translator: TranslationService | None = None,
    translate_semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]]:
    news_items: list[dict[str, Any]] = []

    try:
        df_cls = await asyncio.to_thread(_fetch_cls_raw)
        cls_limit = min(RESEARCH_GLOBAL_NEWS_LIMIT, max(1, RESEARCH_MAX_NEWS_ITEMS // 2))
        for _, row in df_cls.tail(cls_limit).iterrows():
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
    except Exception as e:
        logger.error("[RESEARCH] CLS news collection failed: %s", e)

    try:
        df_futu = await asyncio.to_thread(_fetch_futu_raw)
        futu_limit = min(
            RESEARCH_GLOBAL_NEWS_LIMIT,
            max(1, RESEARCH_MAX_NEWS_ITEMS - len(news_items)),
        )
        for _, row in df_futu.head(futu_limit).iterrows():
            title = _row_value(row, ["标题", "?뉔쥦"], 0)
            content = _row_value(row, ["内容", "?끻?"], 1)
            published_at = _row_value(row, ["发布时间", "?묈툋?띌뿴"], 2)
            url = _row_value(row, ["链接", "?얏렏"], 3)
            if title or content:
                mentioned_stocks: list[str] = []
                theme_candidates: list[dict[str, Any]] = []
                translated_title = title
                translated_content = content
                if translator is not None and translate_semaphore is not None:
                    try:
                        translated = await _translate_article(
                            translator,
                            translate_semaphore,
                            "futu",
                            title,
                            content,
                        )
                        translated_title = translated.title
                        translated_content = translated.content
                        mentioned_stocks = translated.mentioned_stocks
                        theme_candidates = translated.theme_candidates
                    except Exception as e:
                        logger.error("[RESEARCH] Futu translation failed: %s", e)
                        if _is_timeout_error(e):
                            break
                        continue
                news_items.append(
                    _make_news_item(
                        "Futu",
                        translated_title,
                        translated_content,
                        published_at,
                        url,
                        mentioned_stocks=mentioned_stocks,
                        theme_candidates=theme_candidates,
                    )
                )
            if len(news_items) >= RESEARCH_MAX_NEWS_ITEMS:
                return news_items
    except Exception as e:
        logger.error("[RESEARCH] Futu news collection failed: %s", e)

    return news_items[:RESEARCH_MAX_NEWS_ITEMS]


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


# ── 명령어 핸들러 ─────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if await handle_research_callback(query, context, data):
        return

    if await handle_watchlist_callback(query, context, data):
        return


# ── 진입점 ────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    stock_db = StockDatabase(cache_file=STOCK_DB_FILE, enabled=STOCK_DB_ENABLED)
    stock_db.load_or_build()

    app.bot_data["sent_tracker"]         = SentNewsTracker(SENT_IDS_FILE, MAX_SENT_IDS)
    app.bot_data["watchlist_manager"]    = WatchlistManager(WATCHLIST_FILE)
    app.bot_data["market_view_manager"]  = MarketViewManager(MARKET_VIEW_FILE)
    app.bot_data["research_pending"]     = {}
    app.bot_data["stock_news_first_run"] = True
    app.bot_data["stock_db"]             = stock_db
    ollama_num_gpu = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
    app.bot_data["translator"]           = TranslationService(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("TRANSLATE_MODEL", "gemma4"),
        enabled=os.environ.get("TRANSLATE_ENABLED", "true").lower() == "true",
        timeout=int(os.environ.get("TRANSLATE_TIMEOUT", "60")),
        prompt_dir=PROMPT_DIR,
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
    app.bot_data["research_news_collector"] = collect_global_market_news_items

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CommandHandler("add",   cmd_add))
    app.add_handler(CommandHandler("list",  cmd_list))
    app.add_handler(CommandHandler("research", cmd_research))
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
        "봇 시작됨. %s분마다 재련사(財联社) + 푸투니우니우(富途牛牛) + 관심종목 뉴스 전송.",
        SCHEDULE_INTERVAL_MINUTES,
    )
    logger.info("명령어: /start /help /menu /add /list /research")
    app.run_polling()


if __name__ == "__main__":
    main()
