"""스케줄러가 주기적으로 호출하는 뉴스 수집·번역·묶음 전송 파이프라인.

전역 속보는 NewsSourceRegistry의 활성 소스를 함께 조회하고 소스별 기사를
번역한 뒤, 텔레그램 메시지 크기에 맞춘 다이제스트로 묶어 전송한다.

번역 건수(NEWS_GLOBAL_LIMIT)와 송출 건수(NEWS_DIGEST_SEND_LIMIT)는 다르다.
번역한 기사 중 impact가 높은 순으로 골라 보내고, 탈락한 기사도 로그에는
그대로 남긴다(`archive_unsent_articles`).
"""

import asyncio
import html
import logging
from dataclasses import dataclass

import requests
from telegram import Bot
from telegram.ext import Application

from core.config import (
    NEWS_DIGEST_MESSAGE_MAX_CHARS,
    NEWS_DIGEST_SEND_LIMIT,
    NEWS_GLOBAL_LIMIT,
    NEWS_LIVE_MAX_AGE_HOURS,
    NEWS_NEGATIVE_ALERT_THRESHOLD,
    NEWS_SENTIMENT_ENABLED,
    NEWS_SOURCE_MARKETS,
    NEWS_SOURCE_FETCH_TIMEOUT_SECONDS,
    TELEGRAM_CHAT_ID,
)
from core.workers import urgent_phase
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
    signal_codes,
    translate_article,
)
from state import NewsLog, PredictionLog, SentNewsTracker
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


_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


def _digest_priority(index: int, row: PreparedGlobalArticle) -> tuple[int, int, float, int]:
    """송출 우선순위 정렬 키(작을수록 먼저 보낸다).

    impact가 1순위, 같으면 감성의 세기, 그래도 같으면 최신순이다. impact나
    sentiment가 없는 건은 같은 순위 안에서 제일 뒤로 민다.
    """
    translated = row.translated
    sentiment = translated.sentiment
    return (
        _IMPACT_RANK.get(translated.impact, len(_IMPACT_RANK)),
        0 if sentiment is not None else 1,
        -abs(sentiment) if sentiment is not None else 0.0,
        # prepared_rows는 과거→최신 순이라 index가 클수록 새 기사다.
        -index,
    )


def select_digest_rows(
    rows: list[PreparedGlobalArticle],
    send_limit: int,
) -> tuple[list[PreparedGlobalArticle], list[PreparedGlobalArticle]]:
    """번역된 소스 하나의 기사를 (송출 대상, 탈락)으로 나눈다.

    골라낸 쪽은 원래의 과거→최신 표시 순서를 유지한다. 탈락한 쪽도 번역과
    감성 분석은 이미 끝났으므로 버리지 않는다 — 확정과 로그 기록은
    `archive_unsent_articles`가 맡는다.
    """
    if len(rows) <= send_limit:
        return list(rows), []
    ranked = sorted(
        range(len(rows)),
        key=lambda index: _digest_priority(index, rows[index]),
    )
    selected = set(ranked[:send_limit])
    return (
        [row for index, row in enumerate(rows) if index in selected],
        [row for index, row in enumerate(rows) if index not in selected],
    )


async def _confirm_and_log_global_article(
    prepared: PreparedGlobalArticle,
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """처리를 마친 기사를 확정한 뒤 원문 기반 감성 결과를 로그에 기록한다."""
    spec = prepared.spec
    article = prepared.article
    translated = prepared.translated
    await tracker.confirm(article.article_id)

    codes = signal_codes(translated.mentioned_stocks)
    market = str(
        article.extra.get("market")
        or NEWS_SOURCE_MARKETS.get(spec.key.lower())
        or spec.market
        or "OTHER"
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
        # 이미 확정한 뒤이므로 예약을 풀어 같은 기사를 다시 처리하지 않는다.
        logger.error("[%s] 확정 후 로그 기록 실패: %s", spec.key, e)


async def archive_unsent_articles(
    rows: list[PreparedGlobalArticle],
    tracker: SentNewsTracker,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """송출에서 탈락한 기사를 전송 시도 없이 확정하고 로그에만 남긴다.

    release하면 다음 주기에 같은 기사를 다시 집어 다시 번역한다. impact가
    계속 낮으면 영원히 재번역되며 Neurons만 태우므로 확정까지 마친다.
    """
    if not rows:
        return
    for row in rows:
        await _confirm_and_log_global_article(row, tracker, prediction_log, news_log)
    logger.info("[GLOBAL] 송출 제외 %d건은 로그에만 기록", len(rows))


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
    max_body_length = NEWS_DIGEST_MESSAGE_MAX_CHARS - _DIGEST_HEADER_RESERVE
    # chunk_message_items는 아이템 하나가 상한을 넘어도 쪼개지 못한다. 소스 하나의
    # 기사 묶음이 한 메시지에 안 들어가면 텔레그램 4096자 제한에 걸려 전송이
    # 통째로 실패하므로, 섹션을 만들 때 소스 안에서 먼저 나눠 둔다.
    # (기사당 URL 500자 + 본문 상한이 겹치면 소스당 3~4건에서도 넘길 수 있다.)
    sections: list[PreparedSourceSection] = []
    for rows in grouped_rows.values():
        label = f"<b>[{html.escape(rows[0].spec.label)}]</b>\n"
        for row_group in chunk_message_items(
            rows,
            text_getter=lambda row: row.text,
            max_body_length=max(1, max_body_length - len(label)),
            separator=_DIGEST_ARTICLE_SEPARATOR,
        ):
            sections.append(
                PreparedSourceSection(
                    rows=row_group,
                    text=label
                    + _DIGEST_ARTICLE_SEPARATOR.join(row.text for row in row_group),
                )
            )
    chunks = chunk_message_items(
        sections,
        text_getter=lambda section: section.text,
        max_body_length=max_body_length,
        separator=_DIGEST_SOURCE_SEPARATOR,
    )
    # 섹션은 분할될 수 있으므로 소스 수는 그룹 수로 센다.
    source_count = len(grouped_rows)
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

    selected_specs = registry.active_specs()
    if not selected_specs:
        logger.warning("[GLOBAL] 사용 가능한 전역 뉴스 소스가 없습니다(전부 쿨다운).")
    logger.info(
        "[GLOBAL] 이번 주기 처리 소스 %d개: %s",
        len(selected_specs),
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
    # 번역은 소스당 NEWS_GLOBAL_LIMIT건까지 하되, 실제로 보내는 건 impact
    # 상위 NEWS_DIGEST_SEND_LIMIT건이다. 선별은 소스 안에서만 겨룬다.
    prepared_rows: list[PreparedGlobalArticle] = []
    unsent_rows: list[PreparedGlobalArticle] = []
    for group in prepared_groups:
        selected, dropped = select_digest_rows(group, NEWS_DIGEST_SEND_LIMIT)
        prepared_rows.extend(selected)
        unsent_rows.extend(dropped)

    # 전송 실패 시 release되는 건 송출 대상뿐이다. 탈락분은 전송 경로를 아예
    # 타지 않으므로 다이제스트가 실패해도 영향받지 않는다.
    await send_global_digest(
        app.bot,
        TELEGRAM_CHAT_ID,
        prepared_rows,
        tracker,
        prediction_log,
        news_log,
    )
    await archive_unsent_articles(unsent_rows, tracker, prediction_log, news_log)

    await tracker.persist()
