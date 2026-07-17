"""스케줄러가 주기적으로 호출하는 뉴스 수집·번역·전송 파이프라인.

전역 속보는 NewsSourceRegistry에 등록된 소스를 회전 처리하며, 소스별
수집·번역·전송 흐름은 process_global_source 하나로 공통화되어 있다.
"""

import asyncio
import html
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests
from telegram import Bot
from telegram.ext import Application

from core.config import (
    GLOBAL_NEWS_BATCH_SIZE,
    NEWS_GLOBAL_LIMIT,
    NEWS_NEGATIVE_ALERT_THRESHOLD,
    NEWS_SOURCE_MARKETS,
    NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    NEWS_STOCK_LIMIT_PER_SYMBOL,
    STOCK_NEWS_BATCH_SIZE,
    STOCK_NEWS_FETCH_DELAY_SECONDS,
    TELEGRAM_CHAT_ID,
)
from core.workers import run_non_urgent
from news.registry import NewsSourceRegistry, SourceSpec
from news.sources import GlobalArticle, fetch_stock_news_raw as _fetch_stock_news_raw
from news.utils import (
    build_news_message,
    format_china_time_as_kst,
    format_sentiment_line,
    is_timeout_error,
    normalize_stock_code,
    select_rotating_batch,
    signal_codes,
    translate_article,
)
from state import NewsLog, PredictionLog, SentNewsTracker
from stocks import StockDatabase
from llm.translator import TranslationService
from watchlist import WatchlistManager

logger = logging.getLogger(__name__)


# ── 뉴스 수집 함수 ────────────────────────────────────

async def _fetch_source(func, *args):
    return await asyncio.wait_for(
        asyncio.to_thread(func, *args),
        timeout=NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    )


def _watchlist_hits(codes: list[str], watchlist: dict[str, str]) -> list[str]:
    return [
        normalized
        for code in codes
        if (normalized := normalize_stock_code(code)) in watchlist
    ]


def _negative_alert_prefix(sentiment: float | None, related_to_watchlist: bool) -> str:
    if (
        related_to_watchlist
        and sentiment is not None
        and sentiment <= NEWS_NEGATIVE_ALERT_THRESHOLD
    ):
        return "⚠️ <b>관심종목 부정 뉴스</b>\n"
    return ""


async def process_global_source(
    spec: SourceSpec,
    registry: NewsSourceRegistry,
    bot: Bot,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    chat_id: str,
    stock_db: StockDatabase,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
    watchlist: dict[str, str],
) -> None:
    try:
        articles: list[GlobalArticle] = await _fetch_source(spec.fetch)
        registry.record_success(spec.key)
    except TimeoutError:
        registry.record_failure(spec.key, "timeout")
        logger.error(
            "[%s] API 호출 시간 초과: %.1f초", spec.key, NEWS_SOURCE_FETCH_TIMEOUT_SECONDS
        )
        return
    except Exception as e:
        is_rss_blocked = (
            spec.key.startswith("rss:")
            and isinstance(e, requests.HTTPError)
            and e.response is not None
            and e.response.status_code in (403, 429)
        )
        if spec.key.startswith("rss:") and (isinstance(e, requests.Timeout) or is_rss_blocked):
            registry.record_unavailable(spec.key, str(e))
        elif isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 429:
            registry.record_rate_limited(spec.key, str(e))
        else:
            registry.record_failure(spec.key, str(e))
        logger.error("[%s] API 호출 실패: %s", spec.key, e)
        return

    if not articles:
        logger.info("[%s] 수집 기사 0건: 전송할 새 기사가 없습니다.", spec.key)
        return

    metrics = {"duplicate": 0, "translate_failed": 0, "prepared": 0, "sent": 0}

    async def prepare_article(article: GlobalArticle, already_reserved: bool = False):
        article_id = article.article_id
        try:
            if not already_reserved and not await tracker.reserve(article_id):
                metrics["duplicate"] += 1
                return None
            translated = await translate_article(
                translator,
                translate_semaphore,
                spec.prompt_key,
                article.title,
                article.content,
            )
            mentioned_stocks = [
                (code, name)
                for code in translated.mentioned_stocks
                if (name := stock_db.get_display_name(code))
            ]
            link_part = (
                f'\n링크: <a href="{html.escape(article.url)}">{html.escape(article.url)}</a>'
                if article.url
                else ""
            )
            hits = _watchlist_hits(translated.mentioned_stocks, watchlist)
            header = (
                _negative_alert_prefix(translated.sentiment, bool(hits))
                + f"<b>{html.escape(spec.label)} 속보</b>\n"
                f"시간: {format_china_time_as_kst(article.published_at, article.published_date or None)}\n"
                f"{format_sentiment_line(translated.sentiment, translated.impact)}\n"
            )
            text = build_news_message(
                header=header,
                title=translated.title,
                content=translated.content,
                footer=link_part,
                mentioned_stocks=mentioned_stocks,
            )
            metrics["prepared"] += 1
            return article_id, text, translated
        except Exception as e:
            await tracker.release(article_id)
            metrics["translate_failed"] += 1
            logger.error("[%s] 번역 실패: %s", spec.key, e)
            if is_timeout_error(e):
                raise
            return None

    # 앞부분의 중복 기사 때문에 새 기사를 놓치지 않도록 충분한 범위에서
    # 미전송 기사만 먼저 고른 뒤, 과거→최신 순서로 번역·전송한다.
    scan_limit = max(NEWS_GLOBAL_LIMIT * 20, NEWS_GLOBAL_LIMIT)
    selected_articles: list[GlobalArticle] = []
    for article in articles[:scan_limit]:
        if await tracker.reserve(article.article_id):
            selected_articles.append(article)
            if len(selected_articles) >= NEWS_GLOBAL_LIMIT:
                break
        else:
            metrics["duplicate"] += 1

    prepared_rows = []
    for article in selected_articles[::-1]:
        try:
            prepared_rows.append(await prepare_article(article, already_reserved=True))
        except Exception:
            logger.error("[%s] 타임아웃으로 이번 주기 남은 번역을 중단합니다.", spec.key)
            break

    for prepared in prepared_rows:
        if prepared is None:
            continue
        article_id, text, translated = prepared
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            await tracker.confirm(article_id)
            codes = signal_codes(translated.mentioned_stocks)
            market = str(article.extra.get("market") or NEWS_SOURCE_MARKETS.get(spec.key.lower(), "OTHER"))
            if prediction_log is not None and translated.sentiment is not None:
                await prediction_log.record(
                    source=spec.key,
                    title=translated.title,
                    sentiment=translated.sentiment,
                    impact=translated.impact,
                    codes=codes,
                    market=market,
                )
            if news_log is not None:
                await news_log.record(
                    source=spec.key,
                    title=translated.title,
                    sentiment=translated.sentiment,
                    impact=translated.impact,
                    codes=codes,
                    market=market,
                    article_id=article_id,
                )
            metrics["sent"] += 1
            logger.info("[%s] 전송 완료: %s", spec.key, translated.title[:30])
        except Exception as e:
            await tracker.release(article_id)
            logger.error("[%s] 전송 실패: %s", spec.key, e)

    logger.info(
        "[%s] 기사 처리: 수집 %d / 확인 %d / 중복 %d / 번역 준비 %d / 번역 실패 %d / 전송 %d",
        spec.key,
        len(articles),
        min(len(articles), scan_limit),
        metrics["duplicate"],
        metrics["prepared"],
        metrics["translate_failed"],
        metrics["sent"],
    )


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

    prediction_log: PredictionLog | None = bot_data.get("prediction_log")
    news_log: NewsLog | None = bot_data.get("news_log")

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
                    "브리핑: /briefing morning | evening | scorecard\n"
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
            df = await _fetch_source(_fetch_stock_news_raw, code)
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
                    header = (
                        _negative_alert_prefix(translated.sentiment, True)
                        + f"<b>{html.escape(name)} ({code}) 뉴스</b>\n"
                        f"시간: {format_china_time_as_kst(row['发布时间'])}\n"
                        f"출처: {source}\n"
                        f"{format_sentiment_line(translated.sentiment, translated.impact)}\n"
                    )
                    text = build_news_message(
                        header=header,
                        title=translated.title,
                        content=translated.content,
                        footer=f"\n\n링크: {link}",
                    )
                    return article_id, text, translated
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
                article_id, text, translated = prepared
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                    )
                    await tracker.confirm(article_id)
                    if prediction_log is not None and translated.sentiment is not None:
                        await prediction_log.record(
                            source="stock",
                            title=translated.title,
                            sentiment=translated.sentiment,
                            impact=translated.impact,
                            codes=[code],
                            market=NEWS_SOURCE_MARKETS.get("stock", "CN"),
                        )
                    if news_log is not None:
                        await news_log.record(
                            source="stock",
                            title=translated.title,
                            sentiment=translated.sentiment,
                            impact=translated.impact,
                            codes=[code],
                            market=NEWS_SOURCE_MARKETS.get("stock", "CN"),
                            article_id=article_id,
                        )
                    logger.info("[STOCK] 전송 완료: %s %s", name, translated.title[:20])
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 전송 실패: %s", name, e)
        except Exception as e:
            logger.error("[STOCK] %s 오류: %s", name, e)



async def refresh_stock_db(stock_db: StockDatabase) -> None:
    try:
        await run_non_urgent(stock_db.build)
        logger.info("[StockDB] 일별 갱신 완료")
    except Exception as e:
        logger.warning("[StockDB] 일별 갱신 실패: %s", e)


async def fetch_all(app: Application) -> None:
    tracker: SentNewsTracker = app.bot_data["sent_tracker"]
    wm: WatchlistManager     = app.bot_data["watchlist_manager"]
    translator: TranslationService = app.bot_data["translator"]
    translate_semaphore: asyncio.Semaphore = app.bot_data["translate_semaphore"]
    stock_db: StockDatabase = app.bot_data["stock_db"]
    registry: NewsSourceRegistry = app.bot_data["news_registry"]
    prediction_log: PredictionLog | None = app.bot_data.get("prediction_log")
    news_log: NewsLog | None = app.bot_data.get("news_log")
    watchlist = await wm.get_all()

    # 쿨다운 중이 아닌 소스만 회전 처리한다. 쿨다운이 끝난 소스는 자동 복귀.
    active_specs = registry.active_specs()
    if not active_specs:
        logger.warning("[GLOBAL] 사용 가능한 전역 뉴스 소스가 없습니다(전부 쿨다운).")
    cursor = app.bot_data.get("global_news_cursor", 0)
    selected_specs, next_cursor = select_rotating_batch(
        active_specs, cursor, GLOBAL_NEWS_BATCH_SIZE
    )
    app.bot_data["global_news_cursor"] = next_cursor
    logger.info(
        "[GLOBAL] 이번 주기 처리 소스 %d/%d (커서 %d->%d): %s",
        len(selected_specs),
        len(active_specs),
        cursor,
        next_cursor,
        ", ".join(spec.key for spec in selected_specs),
    )
    for spec in selected_specs:
        await process_global_source(
            spec,
            registry,
            app.bot,
            tracker,
            translator,
            translate_semaphore,
            TELEGRAM_CHAT_ID,
            stock_db,
            prediction_log,
            news_log,
            watchlist,
        )

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
