"""스케줄러가 주기적으로 호출하는 뉴스 수집·번역·전송 파이프라인."""

import asyncio
import html
import logging
from datetime import datetime, timedelta

import pandas as pd
from telegram import Bot
from telegram.ext import Application

from core.config import (
    GLOBAL_NEWS_BATCH_SIZE,
    NEWS_GLOBAL_LIMIT,
    NEWS_STOCK_LIMIT_PER_SYMBOL,
    STOCK_NEWS_BATCH_SIZE,
    STOCK_NEWS_FETCH_DELAY_SECONDS,
    TELEGRAM_CHAT_ID,
)
from news.sources import (
    fetch_cls_raw as _fetch_cls_raw,
    fetch_futu_raw as _fetch_futu_raw,
    fetch_stock_news_raw as _fetch_stock_news_raw,
)
from news.utils import (
    build_news_message,
    format_china_time_as_kst,
    is_timeout_error,
    select_rotating_batch,
    translate_article,
)
from state import SentNewsTracker
from stocks import StockDatabase
from llm.translator import TranslationService
from watchlist import WatchlistManager

logger = logging.getLogger(__name__)


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
            translated = await translate_article(
                translator,
                translate_semaphore,
                "cls",
                raw_title,
                raw_content,
            )
            mentioned_stocks = [
                (code, name)
                for code in translated.mentioned_stocks
                if (name := stock_db.get_display_name(code))
            ]
            text = build_news_message(
                header=(
                    f"<b>재련사(財联社) 속보</b>\n"
                    f"시간: {format_china_time_as_kst(row['发布时间'], row['发布日期'])}\n\n"
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
        *(prepare_row(row) for _, row in df.tail(NEWS_GLOBAL_LIMIT).iterrows())
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
            translated = await translate_article(
                translator,
                translate_semaphore,
                "futu",
                raw_title,
                raw_content,
            )
            mentioned_stocks = [
                (code, name)
                for code in translated.mentioned_stocks
                if (name := stock_db.get_display_name(code))
            ]
            link_url = str(row.get("链接") or "")
            link_part = (
                f'\n링크: <a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                if link_url else ""
            )
            text = build_news_message(
                header=(
                    f"<b>푸투니우니우(富途牛牛) 속보</b>\n"
                    f"시간: {format_china_time_as_kst(row['发布时间'])}\n\n"
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
            if is_timeout_error(e):
                raise
            return None

    prepared_rows = []
    for _, row in df.head(NEWS_GLOBAL_LIMIT).iloc[::-1].iterrows():
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
                    "리서치: /research show | set | run | clear\n"
                    "시스템: /system | /system gpu on | off\n"
                    "도움말: /help\n\n"
                    f"{stock_list}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("첫 실행 안내 전송 실패: %s", e)
    bot_data["stock_news_first_run"] = False

    async def send_no_recent_news(name: str) -> None:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"{html.escape(name)}은 최근 7일간 뉴스가 없습니다.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("[STOCK] %s 최근 뉴스 없음 안내 전송 실패: %s", name, e)

    # 전체 종목을 매 주기 일괄 처리하지 않고, 커서를 기준으로 일부만 회전 처리한다.
    codes = list(watchlist.keys())
    cursor = bot_data.get("stock_news_cursor", 0)
    selected_codes, next_cursor = select_rotating_batch(
        codes, cursor, STOCK_NEWS_BATCH_SIZE
    )
    bot_data["stock_news_cursor"] = next_cursor
    logger.info(
        "[STOCK] 이번 주기 처리 대상 %d/%d종목 (커서 %d→%d): %s",
        len(selected_codes),
        len(codes),
        cursor,
        next_cursor,
        ", ".join(selected_codes),
    )

    for batch_index, code in enumerate(selected_codes):
        name = watchlist[code]
        if batch_index > 0 and STOCK_NEWS_FETCH_DELAY_SECONDS > 0:
            await asyncio.sleep(STOCK_NEWS_FETCH_DELAY_SECONDS)
        try:
            df = await asyncio.to_thread(_fetch_stock_news_raw, code)
            if df.empty:
                await send_no_recent_news(name)
                continue

            cutoff = datetime.now() - timedelta(days=7)
            df = df[pd.to_datetime(df["发布时间"], errors="coerce") >= cutoff]
            if df.empty:
                await send_no_recent_news(name)
                continue

            async def prepare_row(row):
                article_id = str(row["发布时间"]) + str(row["新闻标题"])[:20]
                try:
                    if not await tracker.reserve(article_id):
                        return None
                    raw_title = str(row["新闻标题"])
                    raw_content = str(row["新闻内容"])
                    translated = await translate_article(
                        translator,
                        translate_semaphore,
                        "stock",
                        raw_title,
                        raw_content,
                    )
                    source = html.escape(str(row["文章来源"]))
                    link_url = str(row["新闻链接"])
                    link = f'<a href="{html.escape(link_url)}">{html.escape(link_url)}</a>'
                    text = build_news_message(
                        header=(
                            f"<b>{html.escape(name)} ({code}) 뉴스</b>\n"
                            f"시간: {format_china_time_as_kst(row['发布时间'])}\n"
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
                *(prepare_row(row) for _, row in df.head(NEWS_STOCK_LIMIT_PER_SYMBOL).iterrows())
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



async def refresh_stock_db(stock_db: StockDatabase) -> None:
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

    # 전역 속보 소스(CLS/Futu)도 매 주기 전부 처리하지 않고 커서로 회전 분산한다.
    global_sources = [
        (
            "CLS",
            lambda: fetch_cls(
                app.bot, tracker, translator, translate_semaphore, TELEGRAM_CHAT_ID, stock_db
            ),
        ),
        (
            "FUTU",
            lambda: fetch_futu(
                app.bot, tracker, translator, translate_semaphore, TELEGRAM_CHAT_ID, stock_db
            ),
        ),
    ]
    cursor = app.bot_data.get("global_news_cursor", 0)
    selected_sources, next_cursor = select_rotating_batch(
        global_sources, cursor, GLOBAL_NEWS_BATCH_SIZE
    )
    app.bot_data["global_news_cursor"] = next_cursor
    logger.info(
        "[GLOBAL] 이번 주기 처리 소스 %d/%d (커서 %d→%d): %s",
        len(selected_sources),
        len(global_sources),
        cursor,
        next_cursor,
        ", ".join(name for name, _ in selected_sources),
    )
    for _, runner in selected_sources:
        await runner()

    await fetch_stock_news(
        app.bot,
        tracker,
        translator,
        translate_semaphore,
        wm,
        TELEGRAM_CHAT_ID,
        app.bot_data,
        stock_db,
    )
    await tracker.persist()
