import asyncio
import html
import logging
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests.exceptions
from telegram import Bot
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from data.store import SentNewsTracker, WatchlistManager
from data.stock_db import StockDatabase
from llm.translator import TranslationService
from settings import Settings

logger = logging.getLogger(__name__)


def _retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )(func)


@_retry_on_network
def _fetch_cls_raw():
    return ak.stock_info_global_cls()


@_retry_on_network
def _fetch_futu_raw():
    return ak.stock_info_global_futu()


@_retry_on_network
def _fetch_stock_news_raw(symbol: str):
    return ak.stock_news_em(symbol=symbol)


def _build_news_message(
    header: str,
    title: str,
    content: str,
    footer: str = "",
    related_stocks: list[tuple[str, str]] | None = None,
    message_limit: int = 4096,
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
        if len(text) <= message_limit:
            return text

        overflow = len(text) - message_limit
        keep = max(0, len(raw_content) - overflow - len(truncation) - 20)
        next_content = raw_content[:keep].rstrip() + truncation
        if next_content == raw_content:
            text = f"{header}{title_part}{related_line}{footer}"
            return text[: message_limit - len(truncation)] + truncation
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


async def fetch_cls(
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    chat_id: str,
    stock_db: StockDatabase,
    settings: Settings,
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
                translator, translate_semaphore, "cls", raw_title, raw_content,
            )
            related_stocks = [
                (code, name)
                for code in related_codes
                if (name := stock_db.get_cn_name(code))
            ]
            text = _build_news_message(
                header=(
                    f"<b>財联社(재경사) 속보</b>\n"
                    f"🕐 {row['发布日期']} {row['发布时间']}\n\n"
                ),
                title=title,
                content=content,
                related_stocks=related_stocks,
                message_limit=settings.telegram_message_limit,
            )
            return article_id, text, title
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[CLS] 번역 실패: %s", e)
            return None

    prepared_rows = await asyncio.gather(
        *(prepare_row(row) for _, row in df.tail(settings.cls_futu_news_limit).iterrows())
    )

    for prepared in prepared_rows:
        if prepared is None:
            continue
        article_id, text, title = prepared
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
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
    settings: Settings,
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
                translator, translate_semaphore, "futu", raw_title, raw_content,
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
                    f"<b>富途牛牛(푸투뉴뉴) 속보</b>\n"
                    f"🕐 {row['发布时间']}\n\n"
                ),
                title=title,
                content=content,
                footer=link_part,
                related_stocks=related_stocks,
                message_limit=settings.telegram_message_limit,
            )
            return article_id, text, content
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[FUTU] 번역 실패: %s", e)
            return None

    prepared_rows = await asyncio.gather(
        *(prepare_row(row) for _, row in df.head(settings.cls_futu_news_limit).iloc[::-1].iterrows())
    )

    for prepared in prepared_rows:
        if prepared is None:
            continue
        article_id, text, content = prepared
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
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
    settings: Settings,
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

            async def prepare_row(row, _name=name, _code=code):
                article_id = str(row["发布时间"]) + str(row["新闻标题"])[:20]
                try:
                    if not await tracker.reserve(article_id):
                        return None
                    raw_title = str(row["新闻标题"])
                    raw_content = str(row["新闻内容"])
                    title, content, related_codes = await _translate_article(
                        translator, translate_semaphore, "stock", raw_title, raw_content,
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
                            f"🏢 <b>{html.escape(_name)} ({_code}) 뉴스</b>\n"
                            f"🕐 {row['发布时间']}\n"
                            f"📌 {source}\n\n"
                        ),
                        title=title,
                        content=content,
                        footer=f"\n\n🔗 {link}",
                        related_stocks=related_stocks,
                        message_limit=settings.telegram_message_limit,
                    )
                    return article_id, text, title
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 번역 실패: %s", _name, e)
                    return None

            prepared_rows = await asyncio.gather(
                *(prepare_row(row) for _, row in df.head(settings.stock_news_limit).iterrows())
            )

            for prepared in prepared_rows:
                if prepared is None:
                    continue
                article_id, text, title = prepared
                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                    await tracker.confirm(article_id)
                    logger.info("[STOCK] 전송 완료: %s %s", name, title[:20])
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 전송 실패: %s", name, e)
        except Exception as e:
            logger.error("[STOCK] %s 오류: %s", name, e)


async def fetch_xinhua(
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    chat_id: str,
    stock_db: StockDatabase,
    settings: Settings,
) -> None:
    if not settings.xinhua_enabled:
        return

    import feedparser

    async def _fetch_entries():
        entries = []
        for feed_url in settings.xinhua_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    title = entry.get("title", "").strip()
                    content = entry.get("summary", entry.get("description", "")).strip()
                    link = entry.get("link", "")
                    published = entry.get("published", "")
                    if title:
                        entries.append({"title": title, "content": content,
                                        "link": link, "published": published})
            except Exception as e:
                logger.error("[XINHUA] RSS fetch failed (%s): %s", feed_url, e)
        return entries

    try:
        entries = await asyncio.to_thread(_fetch_entries)
    except Exception as e:
        logger.error("[XINHUA] fetch failed: %s", e)
        return

    async def prepare_entry(entry):
        article_id = "xinhua:" + entry["title"][:60]
        try:
            if not await tracker.reserve(article_id):
                return None
            title, content, related_codes = await _translate_article(
                translator, translate_semaphore, "xinhua",
                entry["title"], entry["content"],
            )
            related_stocks = [
                (code, name)
                for code in related_codes
                if (name := stock_db.get_cn_name(code))
            ]
            link_part = (
                f'\n🔗 <a href="{html.escape(entry["link"])}">{html.escape(entry["link"])}</a>'
                if entry["link"] else ""
            )
            text = _build_news_message(
                header=(
                    f"🏛 <b>新华社 정책문서</b>\n"
                    f"🕐 {html.escape(entry['published'])}\n\n"
                ),
                title=title,
                content=content,
                footer=link_part,
                related_stocks=related_stocks,
                message_limit=settings.telegram_message_limit,
            )
            return article_id, text, title
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[XINHUA] 번역 실패: %s", e)
            return None

    prepared = await asyncio.gather(
        *(prepare_entry(e) for e in entries[:settings.xinhua_news_limit])
    )
    for item in prepared:
        if item is None:
            continue
        article_id, text, title = item
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            await tracker.confirm(article_id)
            logger.info("[XINHUA] 전송 완료: %s", title[:30])
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[XINHUA] 전송 실패: %s", e)


async def _refresh_stock_db(stock_db: StockDatabase) -> None:
    try:
        await asyncio.to_thread(stock_db.build)
        logger.info("[StockDB] 일별 갱신 완료")
    except Exception as e:
        logger.warning("[StockDB] 일별 갱신 실패: %s", e)


async def fetch_all(app) -> None:
    svc = app.bot_data["services"]
    settings: Settings = svc.settings
    chat_id = settings.chat_id

    await fetch_cls(
        app.bot, svc.sent_tracker, svc.translator,
        svc.translate_semaphore, chat_id, svc.stock_db, settings,
    )
    await fetch_futu(
        app.bot, svc.sent_tracker, svc.translator,
        svc.translate_semaphore, chat_id, svc.stock_db, settings,
    )
    await fetch_xinhua(
        app.bot, svc.sent_tracker, svc.translator,
        svc.translate_semaphore, chat_id, svc.stock_db, settings,
    )
    await fetch_stock_news(
        app.bot, svc.sent_tracker, svc.translator, svc.translate_semaphore,
        svc.watchlist, chat_id, app.bot_data, svc.stock_db, settings,
    )
    await svc.sent_tracker.persist()
