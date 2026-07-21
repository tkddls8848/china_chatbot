"""스케줄러가 주기적으로 호출하는 뉴스 수집·번역·묶음 전송 파이프라인.

전역 속보는 NewsSourceRegistry의 활성 소스를 함께 조회하고 소스별 기사를
번역한 뒤, 텔레그램 메시지 크기에 맞춘 다이제스트로 묶어 전송한다.
"""

import asyncio
import html
import logging
from dataclasses import dataclass

import requests
from telegram import Bot
from telegram.ext import Application

from core.config import (
    GLOBAL_NEWS_BATCH_SIZE,
    NEWS_DIGEST_MESSAGE_MAX_CHARS,
    NEWS_GLOBAL_LIMIT,
    NEWS_LIVE_MAX_AGE_HOURS,
    NEWS_NEGATIVE_ALERT_THRESHOLD,
    NEWS_SENTIMENT_ENABLED,
    NEWS_SOURCE_MARKETS,
    NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    TELEGRAM_CHAT_ID,
)
from core.workers import run_non_urgent, urgent_phase
from news.registry import NewsSourceRegistry, SourceSpec
from news.sources import GlobalArticle
from news.utils import (
    chunk_message_items,
    compact_kst_time,
    filter_recent_articles,
    format_china_time_as_kst,
    format_digest_article,
    is_timeout_error,
    normalize_stock_code,
    publication_time_naive,
    select_rotating_batch,
    signal_codes,
    translate_article,
)
from state import NewsLog, PredictionLog, SentNewsTracker
from stocks import StockDatabase
from llm.translator import TranslationResult, TranslationService
from watchlist import WatchlistManager

logger = logging.getLogger(__name__)
_DIGEST_ARTICLE_SEPARATOR = "\n\n"
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
        return "- 감성 : 분석 불가"
    if sentiment >= 0.15:
        marker = "긍정"
    elif sentiment <= -0.15:
        marker = "부정"
    else:
        marker = "중립"
    impact_labels = {"high": "높음", "medium": "중간", "low": "낮음"}
    impact_part = (
        f" · 영향 {impact_labels[impact]}"
        if impact in impact_labels
        else ""
    )
    return f"- 감성 : {marker} {sentiment:+.2f}{impact_part}"


async def prepare_global_source(
    spec: SourceSpec,
    registry: NewsSourceRegistry,
    tracker: SentNewsTracker,
    translator: TranslationService,
    translate_semaphore: asyncio.Semaphore,
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

    fetched_count = len(articles)
    articles = filter_recent_articles(articles, NEWS_LIVE_MAX_AGE_HOURS)
    if not articles:
        logger.info(
            "[%s] 발행시각 필터 후 기사 0건 (수집 %d건, 최근 %d시간)",
            spec.key,
            fetched_count,
            NEWS_LIVE_MAX_AGE_HOURS,
        )
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
            text = format_digest_article(
                translated.title,
                translated.content,
                compact_kst_time(formatted_time),
                sentiment_line,
                alert,
                safe_url,
            )
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
        fetched_count,
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
                occurred_at=publication_time_naive(
                    article.published_at,
                    article.published_date or None,
                ),
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


async def refresh_stock_db(stock_db: StockDatabase) -> None:
    try:
        await run_non_urgent(stock_db.build)
        logger.info("[StockDB] 일별 갱신 완료")
    except Exception as e:
        logger.warning("[StockDB] 일별 갱신 실패: %s", e)


async def fetch_all(app: Application) -> None:
    """뉴스 수집·번역 주기(긴급 경로).

    이 구간이 도는 동안 리서치·브리핑 등 비긴급 LLM 작업은 시작을 보류해,
    번역이 그 뒤에서 대기하지 않도록 한다.
    """
    async with urgent_phase():
        await _fetch_all(app)


async def _fetch_all(app: Application) -> None:
    tracker: SentNewsTracker = app.bot_data["sent_tracker"]
    wm: WatchlistManager     = app.bot_data["watchlist_manager"]
    translator: TranslationService = app.bot_data["translator"]
    translate_semaphore: asyncio.Semaphore = app.bot_data["translate_semaphore"]
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

    await tracker.persist()
