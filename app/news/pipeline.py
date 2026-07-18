"""스케줄러가 주기적으로 호출하는 뉴스 수집·번역·묶음 전송 파이프라인.

전역 속보는 NewsSourceRegistry의 활성 소스를 함께 조회하고 소스별 기사를
번역한 뒤, 텔레그램 메시지 크기에 맞춘 다이제스트로 묶어 전송한다.
"""

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
import requests
from telegram import Bot
from telegram.ext import Application

from core.config import (
    GLOBAL_NEWS_BATCH_SIZE,
    NEWS_DIGEST_MESSAGE_MAX_CHARS,
    NEWS_GLOBAL_LIMIT,
    NEWS_NEGATIVE_ALERT_THRESHOLD,
    NEWS_SENTIMENT_ENABLED,
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
    chunk_message_items,
    format_china_time_as_kst,
    is_timeout_error,
    normalize_stock_code,
    select_rotating_batch,
    signal_codes,
    truncate_text,
    translate_article,
)
from state import NewsLog, PredictionLog, SentNewsTracker
from stocks import StockDatabase
from llm.translator import TranslationResult, TranslationService
from watchlist import WatchlistManager

logger = logging.getLogger(__name__)
_DIGEST_ARTICLE_SEPARATOR = "\n"
_DIGEST_SOURCE_SEPARATOR = "\n\n"
_DIGEST_HEADER_RESERVE = 160


@dataclass(frozen=True)
class PreparedGlobalArticle:
    spec: SourceSpec
    article: GlobalArticle
    text: str
    translated: TranslationResult


@dataclass(frozen=True)
class PreparedSourceSection:
    rows: list[PreparedGlobalArticle]
    text: str


@dataclass(frozen=True)
class PreparedStockArticle:
    code: str
    name: str
    article_id: str
    text: str
    translated: TranslationResult


@dataclass(frozen=True)
class PreparedStockSection:
    rows: list[PreparedStockArticle]
    text: str


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


def _compact_sentiment_line(sentiment: float | None, impact: str = "") -> str:
    if not NEWS_SENTIMENT_ENABLED:
        return ""
    if sentiment is None:
        return "- 감성: 분석 불가"
    if sentiment >= 0.15:
        marker = "🟢"
    elif sentiment <= -0.15:
        marker = "🔴"
    else:
        marker = "⚪"
    impact_labels = {"high": "높음", "medium": "중간", "low": "낮음"}
    impact_part = (
        f" · 영향 {impact_labels[impact]}"
        if impact in impact_labels
        else ""
    )
    return f"- 감성: {marker} {sentiment:+.2f}{impact_part}"


async def prepare_global_source(
    spec: SourceSpec,
    registry: NewsSourceRegistry,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
    stock_db: StockDatabase,
    watchlist: dict[str, str],
) -> list[PreparedGlobalArticle]:
    try:
        articles: list[GlobalArticle] = await _fetch_source(spec.fetch)
        registry.record_success(spec.key)
    except TimeoutError:
        registry.record_failure(spec.key, "timeout")
        logger.error(
            "[%s] API 호출 시간 초과: %.1f초", spec.key, NEWS_SOURCE_FETCH_TIMEOUT_SECONDS
        )
        return []
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
        return []

    if not articles:
        logger.info("[%s] 수집 기사 0건: 전송할 새 기사가 없습니다.", spec.key)
        return []

    metrics = {"duplicate": 0, "translate_failed": 0, "prepared": 0}

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
            safe_url = article.url if len(article.url) <= 500 else ""
            link_part = (
                f' · <a href="{html.escape(safe_url)}">원문</a>'
                if safe_url
                else ""
            )
            hits = _watchlist_hits(translated.mentioned_stocks, watchlist)
            sentiment_line = _compact_sentiment_line(
                translated.sentiment,
                translated.impact,
            )
            alert = (
                "⚠️ "
                if _negative_alert_prefix(translated.sentiment, bool(hits))
                else ""
            )
            formatted_time = format_china_time_as_kst(
                article.published_at,
                article.published_date or None,
            )
            time_parts = formatted_time.split()
            compact_time = " ".join(time_parts[-2:]) if len(time_parts) >= 2 else formatted_time
            text = (
                f"• {alert}<b>{html.escape(truncate_text(translated.title, 120))}</b>"
                f" ({html.escape(compact_time)}){link_part}\n"
                f"- {html.escape(translated.content)}"
            )
            if sentiment_line:
                text += f"\n{sentiment_line}"
            metrics["prepared"] += 1
            return PreparedGlobalArticle(spec, article, text, translated)
        except Exception as e:
            await tracker.release(article_id)
            metrics["translate_failed"] += 1
            logger.error("[%s] 번역 실패: %s", spec.key, e)
            if is_timeout_error(e):
                raise
            return None

    # 앞부분의 중복·번역 실패 때문에 소스별 목표 건수를 놓치지 않도록 충분한
    # 범위를 훑는다. 최신 기사부터 준비하고 출력 직전에 과거→최신으로 뒤집는다.
    scan_limit = max(NEWS_GLOBAL_LIMIT * 20, NEWS_GLOBAL_LIMIT)
    scanned = 0
    prepared_rows: list[PreparedGlobalArticle] = []
    for article in articles[:scan_limit]:
        scanned += 1
        if not await tracker.reserve(article.article_id):
            metrics["duplicate"] += 1
            continue
        try:
            prepared = await prepare_article(article, already_reserved=True)
        except Exception:
            logger.error("[%s] 타임아웃으로 이번 주기 남은 번역을 중단합니다.", spec.key)
            break
        if prepared is not None:
            prepared_rows.append(prepared)
            if len(prepared_rows) >= NEWS_GLOBAL_LIMIT:
                break

    logger.info(
        "[%s] 기사 준비: 수집 %d / 확인 %d / 중복 %d / 번역 준비 %d / 번역 실패 %d",
        spec.key,
        len(articles),
        scanned,
        metrics["duplicate"],
        metrics["prepared"],
        metrics["translate_failed"],
    )
    return prepared_rows[::-1]


async def _confirm_and_log_global_article(
    prepared: PreparedGlobalArticle,
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """전송된 기사를 확정한 뒤 원문 기반 감성 결과를 로그에 기록한다."""
    spec = prepared.spec
    article = prepared.article
    translated = prepared.translated
    await tracker.confirm(article.article_id)

    codes = signal_codes(translated.mentioned_stocks)
    market = str(
        article.extra.get("market")
        or NEWS_SOURCE_MARKETS.get(spec.key.lower(), "OTHER")
    )
    try:
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
                article_id=article.article_id,
            )
    except Exception as e:
        # 메시지는 이미 전송됐으므로 예약을 풀어 중복 송출하지 않는다.
        logger.error("[%s] 전송 후 로그 기록 실패: %s", spec.key, e)


async def send_global_digest(
    bot: Bot,
    chat_id: str,
    prepared_rows: list[PreparedGlobalArticle],
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """여러 뉴스사의 기사를 안전 크기의 다이제스트 메시지로 묶어 보낸다."""
    if not prepared_rows:
        return

    grouped_rows: dict[str, list[PreparedGlobalArticle]] = {}
    for row in prepared_rows:
        grouped_rows.setdefault(row.spec.key, []).append(row)
    sections = [
        PreparedSourceSection(
            rows=rows,
            text=(
                f"<b>[{html.escape(rows[0].spec.label)}]</b>\n"
                + _DIGEST_ARTICLE_SEPARATOR.join(row.text for row in rows)
            ),
        )
        for rows in grouped_rows.values()
    ]
    chunks = chunk_message_items(
        sections,
        text_getter=lambda section: section.text,
        max_body_length=NEWS_DIGEST_MESSAGE_MAX_CHARS - _DIGEST_HEADER_RESERVE,
        separator=_DIGEST_SOURCE_SEPARATOR,
    )
    source_count = len(sections)
    article_count = len(prepared_rows)

    for chunk_index, chunk in enumerate(chunks, start=1):
        header = (
            "<b>뉴스 다이제스트</b>\n"
            f"소스 {source_count}곳 · 새 기사 {article_count}건"
            f" · {chunk_index}/{len(chunks)}\n\n"
        )
        text = header + _DIGEST_SOURCE_SEPARATOR.join(
            section.text for section in chunk
        )
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            for section in chunk:
                for row in section.rows:
                    await tracker.release(row.article.article_id)
            logger.error(
                "[GLOBAL] 다이제스트 %d/%d 전송 실패: %s",
                chunk_index,
                len(chunks),
                e,
            )
            continue

        for section in chunk:
            for row in section.rows:
                await _confirm_and_log_global_article(
                    row,
                    tracker,
                    prediction_log,
                    news_log,
                )
                logger.info(
                    "[%s] 다이제스트 전송 완료: %s",
                    row.spec.key,
                    row.translated.title[:30],
                )


async def _confirm_and_log_stock_article(
    prepared: PreparedStockArticle,
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    await tracker.confirm(prepared.article_id)
    translated = prepared.translated
    try:
        if prediction_log is not None and translated.sentiment is not None:
            await prediction_log.record(
                source="stock",
                title=translated.title,
                sentiment=translated.sentiment,
                impact=translated.impact,
                codes=[prepared.code],
                market=NEWS_SOURCE_MARKETS.get("stock", "CN"),
            )
        if news_log is not None:
            await news_log.record(
                source="stock",
                title=translated.title,
                sentiment=translated.sentiment,
                impact=translated.impact,
                codes=[prepared.code],
                market=NEWS_SOURCE_MARKETS.get("stock", "CN"),
                article_id=prepared.article_id,
            )
    except Exception as e:
        logger.error(
            "[STOCK] %s 전송 후 로그 기록 실패: %s",
            prepared.name,
            e,
        )


async def send_stock_digest(
    bot: Bot,
    chat_id: str,
    prepared_rows: list[PreparedStockArticle],
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """관심종목 기사를 종목별 섹션으로 묶어 안전 크기로 전송한다."""
    if not prepared_rows:
        return

    grouped_rows: dict[str, list[PreparedStockArticle]] = {}
    for row in prepared_rows:
        grouped_rows.setdefault(row.code, []).append(row)
    sections = [
        PreparedStockSection(
            rows=rows,
            text=(
                f"<b>[{html.escape(rows[0].name)} ({html.escape(rows[0].code)})]</b>\n"
                + _DIGEST_ARTICLE_SEPARATOR.join(row.text for row in rows)
            ),
        )
        for rows in grouped_rows.values()
    ]
    chunks = chunk_message_items(
        sections,
        text_getter=lambda section: section.text,
        max_body_length=NEWS_DIGEST_MESSAGE_MAX_CHARS - _DIGEST_HEADER_RESERVE,
        separator=_DIGEST_SOURCE_SEPARATOR,
    )
    stock_count = len(sections)
    article_count = len(prepared_rows)

    for chunk_index, chunk in enumerate(chunks, start=1):
        header = (
            "<b>관심종목 뉴스</b>\n"
            f"종목 {stock_count}개 · 새 기사 {article_count}건"
            f" · {chunk_index}/{len(chunks)}\n\n"
        )
        text = header + _DIGEST_SOURCE_SEPARATOR.join(
            section.text for section in chunk
        )
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            for section in chunk:
                for row in section.rows:
                    await tracker.release(row.article_id)
            logger.error(
                "[STOCK] 다이제스트 %d/%d 전송 실패: %s",
                chunk_index,
                len(chunks),
                e,
            )
            continue

        for section in chunk:
            for row in section.rows:
                await _confirm_and_log_stock_article(
                    row,
                    tracker,
                    prediction_log,
                    news_log,
                )
                logger.info(
                    "[STOCK] 다이제스트 전송 완료: %s %s",
                    row.name,
                    row.translated.title[:20],
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

    # 기본 설정에서는 모든 관심종목을 조회하고 결과를 한 다이제스트로 묶는다.
    # STOCK_NEWS_BATCH_SIZE가 양수면 해당 개수만큼 종목을 회전 처리한다.
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

    prepared_stock_rows: list[PreparedStockArticle] = []
    for batch_index, code in enumerate(selected_codes):
        name = watchlist[code]
        if batch_index > 0 and STOCK_NEWS_FETCH_DELAY_SECONDS > 0:
            await asyncio.sleep(STOCK_NEWS_FETCH_DELAY_SECONDS)
        try:
            df = await _fetch_source(_fetch_stock_news_raw, code)
            if df.empty:
                logger.info("[STOCK] %s 수집 기사 0건", name)
                continue

            cutoff = datetime.now() - timedelta(days=7)
            df = df[pd.to_datetime(df["发布时间"], errors="coerce") >= cutoff]
            if df.empty:
                logger.info("[STOCK] %s 최근 7일 기사 0건", name)
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
                    source = str(row["文章来源"])
                    link_url = str(row["新闻链接"])
                    safe_url = link_url if len(link_url) <= 500 else ""
                    link_part = (
                        f' · <a href="{html.escape(safe_url)}">원문</a>'
                        if safe_url
                        else ""
                    )
                    formatted_time = format_china_time_as_kst(row["发布时间"])
                    time_parts = formatted_time.split()
                    compact_time = (
                        " ".join(time_parts[-2:])
                        if len(time_parts) >= 2
                        else formatted_time
                    )
                    alert = (
                        "⚠️ "
                        if _negative_alert_prefix(translated.sentiment, True)
                        else ""
                    )
                    source_part = (
                        f" · {html.escape(truncate_text(source, 30))}"
                        if source
                        else ""
                    )
                    text = (
                        f"• {alert}<b>{html.escape(truncate_text(translated.title, 120))}</b>"
                        f" ({html.escape(compact_time)}){source_part}{link_part}\n"
                        f"- {html.escape(translated.content)}"
                    )
                    sentiment_line = _compact_sentiment_line(
                        translated.sentiment,
                        translated.impact,
                    )
                    if sentiment_line:
                        text += f"\n{sentiment_line}"
                    return PreparedStockArticle(
                        code,
                        name,
                        article_id,
                        text,
                        translated,
                    )
                except Exception as e:
                    await tracker.release(article_id)
                    logger.error("[STOCK] %s 번역 실패: %s", name, e)
                    if is_timeout_error(e):
                        raise
                    return None

            prepared_for_stock: list[PreparedStockArticle] = []
            scan_limit = max(
                NEWS_STOCK_LIMIT_PER_SYMBOL * 20,
                NEWS_STOCK_LIMIT_PER_SYMBOL,
            )
            for _, row in df.head(scan_limit).iterrows():
                try:
                    prepared = await prepare_row(row)
                except Exception:
                    logger.error(
                        "[STOCK] %s 타임아웃으로 이번 종목의 남은 번역을 중단합니다.",
                        name,
                    )
                    break
                if prepared is None:
                    continue
                prepared_for_stock.append(prepared)
                if len(prepared_for_stock) >= NEWS_STOCK_LIMIT_PER_SYMBOL:
                    break
            prepared_stock_rows.extend(prepared_for_stock[::-1])
        except Exception as e:
            logger.error("[STOCK] %s 오류: %s", name, e)

    await send_stock_digest(
        bot,
        chat_id,
        prepared_stock_rows,
        tracker,
        prediction_log,
        news_log,
    )



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

    # 기본 설정에서는 쿨다운 중이 아닌 모든 소스를 한 주기에 함께 처리한다.
    # GLOBAL_NEWS_BATCH_SIZE가 양수면 이전처럼 일부 소스를 회전 처리한다.
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
    prepared_groups = await asyncio.gather(
        *(
            prepare_global_source(
                spec,
                registry,
                tracker,
                translator,
                translate_semaphore,
                stock_db,
                watchlist,
            )
            for spec in selected_specs
        )
    )
    prepared_rows = [row for group in prepared_groups for row in group]
    await send_global_digest(
        app.bot,
        TELEGRAM_CHAT_ID,
        prepared_rows,
        tracker,
        prediction_log,
        news_log,
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
