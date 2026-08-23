"""야간 수집과 아침 야간 다이제스트.

JST 야간(기본 00~07시)에는 기사별 번역을 하지 않는다. 주기는 그대로 돌면서
원문만 큐에 담고, 야간이 끝나는 시각에 시장별로 한 번씩 LLM을 불러 그 시간의
흐름을 한 번에 요약해 보낸다.

같은 7시간을 기사별로 번역하면 소스 6곳 × 시간당 5건 = 210 호출인데, 읽는
사람은 자고 있어 아침에 한 번 읽는다. 여기서 쓰는 호출은 시장 수(최대 4회)다.
"""

import asyncio
import html
import logging
from datetime import datetime

from telegram import Bot
from telegram.ext import Application

from core.clock import JST, now
from core.config import (
    NEWS_DIGEST_MESSAGE_MAX_CHARS,
    NEWS_NIGHT_DIGEST_MAX_HEADLINES,
    NEWS_NIGHT_END_HOUR,
    NEWS_NIGHT_QUEUE_PER_SOURCE_LIMIT,
    NEWS_NIGHT_START_HOUR,
    NEWS_SOURCE_MARKETS,
    TELEGRAM_CHAT_ID,
)
from core.workers import burst_job, run_non_urgent
from llm.night_digest import NightDigestAnalyzer, NightDigestError
from news.collection import collect_source_candidates
from news.registry import NewsSourceRegistry, SourceSpec
from news.utils import (
    chunk_message_items,
    compact_jst_time,
    compact_sentiment_line,
    format_china_time_as_jst,
    format_digest_article,
    parse_news_datetime,
    publication_time_naive,
    signal_codes,
)
from state import NewsLog, NightNewsQueue, PredictionLog, SentNewsTracker
from watchlist import WatchlistManager

logger = logging.getLogger(__name__)

_MARKET_LABELS = {
    "CN": "중국 본토",
    "HK": "홍콩",
    "US": "미국",
    "KR": "한국",
    "JP": "일본",
    "EU": "유럽",
    "OTHER": "기타",
}
# 시장 표시 순서. 목록 밖 시장은 뒤에 붙인다.
_MARKET_ORDER = ("CN", "HK", "US", "KR")
_DIGEST_HEADER_RESERVE = 200
# 요약이 실패한 시장에 원문 제목만 남길 때의 건수.
_FALLBACK_HEADLINE_LIMIT = 10
_EPOCH = datetime(1970, 1, 1, tzinfo=JST)
# 07시 cron job과 주간 첫 주기의 회수 경로가 겹칠 수 있다. 둘 다 큐를 통째로
# 읽고 보내므로, 막지 않으면 같은 다이제스트가 두 번 나간다.
_DIGEST_LOCK = asyncio.Lock()


def is_night_window(moment: datetime | None = None) -> bool:
    """지금이 번역을 멈추는 야간 구간인가(JST).

    시작 > 종료면 자정을 넘는 구간이다(예: 22시~07시).
    """
    hour = (moment or now()).hour
    if NEWS_NIGHT_START_HOUR < NEWS_NIGHT_END_HOUR:
        return NEWS_NIGHT_START_HOUR <= hour < NEWS_NIGHT_END_HOUR
    return hour >= NEWS_NIGHT_START_HOUR or hour < NEWS_NIGHT_END_HOUR


def _market_of(spec: SourceSpec, article) -> str:
    return str(
        article.extra.get("market")
        or NEWS_SOURCE_MARKETS.get(spec.key.lower())
        or spec.market
        or "OTHER"
    )


def _queue_item(candidate) -> dict:
    article = candidate.article
    return {
        "article_id": article.article_id,
        "event_id": candidate.event_id,
        "source": candidate.spec.key,
        "label": candidate.spec.label,
        "market": _market_of(candidate.spec, article),
        "title": article.title[:240],
        "url": article.url if len(article.url) <= 500 else "",
        "published_at": article.published_at,
        "published_date": article.published_date or "",
        "prefilter_candidate_id": candidate.prefilter_candidate_id,
    }


async def collect_night_source(
    spec: SourceSpec,
    registry: NewsSourceRegistry,
    tracker: SentNewsTracker,
    queue: NightNewsQueue,
    watchlist: dict[str, str],
    prefilter=None,
    cycle_id: str = "",
) -> int:
    """소스 하나의 야간 기사를 예약하고 큐에 담는다. 번역하지 않는다."""
    candidates = await collect_source_candidates(
        spec,
        registry,
        watchlist,
        prefilter,
        cycle_id,
    )
    reserved = []
    for candidate in candidates[:NEWS_NIGHT_QUEUE_PER_SOURCE_LIMIT]:
        if await tracker.reserve(candidate.article.article_id):
            reserved.append(candidate)
    if not reserved:
        return 0
    try:
        accepted = await queue.enqueue([_queue_item(row) for row in reserved])
    except Exception as e:
        for row in reserved:
            await tracker.release(row.article.article_id)
        logger.error("[%s] 야간 큐 저장 실패, 예약을 해제합니다: %s", spec.key, e)
        return 0

    accepted_ids = {item["article_id"] for item in accepted}
    for row in reserved:
        # 큐가 받지 않은 것(사건 중복 등)은 다음 주기에 다시 볼 수 있게 둔다.
        if row.article.article_id not in accepted_ids:
            await tracker.release(row.article.article_id)
    return len(accepted)


async def collect_night_articles(app: Application) -> None:
    """야간 주기. 소스를 읽어 큐에만 담고 LLM을 부르지 않는다."""
    tracker: SentNewsTracker = app.bot_data["sent_tracker"]
    queue: NightNewsQueue = app.bot_data["night_queue"]
    registry: NewsSourceRegistry = app.bot_data["news_registry"]
    wm: WatchlistManager = app.bot_data["watchlist_manager"]
    prefilter = app.bot_data.get("news_prefilter")
    watchlist = await wm.get_all()
    cycle_id = now().isoformat(timespec="seconds")

    specs = registry.active_specs()
    if not specs:
        logger.warning("[NIGHT] 사용 가능한 전역 뉴스 소스가 없습니다(전부 쿨다운).")
        return
    counts = await asyncio.gather(
        *(
            collect_night_source(
                spec,
                registry,
                tracker,
                queue,
                watchlist,
                prefilter,
                cycle_id,
            )
            for spec in specs
        )
    )
    await tracker.persist()
    logger.info(
        "[NIGHT] 야간 수집 %d건 (소스 %d곳, 번역하지 않음)",
        sum(counts),
        len(specs),
    )


def _sorted_by_recency(items: list[dict]) -> list[dict]:
    """발행시각 최신순. 시각을 못 읽은 기사는 뒤로 민다."""
    def key(item: dict):
        parsed = parse_news_datetime(item.get("published_at"), item.get("published_date"))
        return (parsed is not None, parsed or _EPOCH)

    return sorted(items, key=key, reverse=True)


def group_by_market(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """시장별로 묶고 표시 순서대로 돌려준다. 시장 안은 최신순이다."""
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(str(item.get("market") or "OTHER"), []).append(item)
    ordered_keys = [key for key in _MARKET_ORDER if key in grouped]
    ordered_keys += sorted(key for key in grouped if key not in _MARKET_ORDER)
    return [(key, _sorted_by_recency(grouped[key])) for key in ordered_keys]


def _window_label(opened_at: str, closed_at: datetime) -> str:
    try:
        opened = datetime.fromisoformat(opened_at)
    except (TypeError, ValueError):
        opened = None
    start = opened.strftime("%H:%M") if opened else f"{NEWS_NIGHT_START_HOUR:02d}:00"
    return f"{start}~{closed_at.strftime('%H:%M')} JST"


def _headline_payload(items: list[dict]) -> list[dict]:
    payload = []
    for index, item in enumerate(items):
        formatted = format_china_time_as_jst(
            item.get("published_at"),
            item.get("published_date") or None,
        )
        payload.append(
            {
                "index": index,
                "title": str(item.get("title") or ""),
                "source": str(item.get("label") or item.get("source") or ""),
                "published_at": compact_jst_time(formatted),
            }
        )
    return payload


def _highlight_text(item: dict, highlight: dict) -> str:
    formatted = format_china_time_as_jst(
        item.get("published_at"),
        item.get("published_date") or None,
    )
    return format_digest_article(
        highlight["title"],
        "",
        compact_jst_time(formatted),
        compact_sentiment_line(highlight["sentiment"], highlight["impact"]),
        "",
        str(item.get("url") or ""),
    )


def format_market_section(
    market: str,
    items: list[dict],
    result: dict | None,
) -> str:
    """시장 하나의 야간 요약 섹션. result가 없으면 제목만 나열한다."""
    label = _MARKET_LABELS.get(market, market)
    lines = [f"<b>[{html.escape(label)}]</b> 수집 {len(items)}건"]
    if result is None:
        # LLM이 실패한 시장이다. 그 시간의 뉴스를 통째로 잃지 않도록 원문
        # 제목만이라도 남긴다.
        lines.append("<i>요약 생성 실패 — 원문 제목만 표시합니다.</i>")
        for item in items[:_FALLBACK_HEADLINE_LIMIT]:
            formatted = format_china_time_as_jst(
                item.get("published_at"),
                item.get("published_date") or None,
            )
            lines.append(
                format_digest_article(
                    str(item.get("title") or ""),
                    "",
                    compact_jst_time(formatted),
                    "",
                    "",
                    str(item.get("url") or ""),
                )
            )
        return "\n\n".join(lines)

    if result["analysis"]:
        lines.append(html.escape(result["analysis"]))
    for highlight in result["highlights"]:
        lines.append(_highlight_text(items[highlight["index"]], highlight))
    return "\n\n".join(lines)


async def _analyze_market(
    analyzer: NightDigestAnalyzer,
    market: str,
    window: str,
    items: list[dict],
) -> dict | None:
    headlines = _headline_payload(items[:NEWS_NIGHT_DIGEST_MAX_HEADLINES])
    try:
        return await run_non_urgent(analyzer.analyze, market, window, headlines)
    except NightDigestError as e:
        logger.error("[NIGHT] %s 야간 요약 실패: %s", market, e)
        return None


async def _log_highlights(
    market: str,
    items: list[dict],
    result: dict,
    prediction_log: PredictionLog | None,
    news_log: NewsLog | None,
) -> None:
    """야간 주요 기사도 주간 번역과 같은 로그에 남긴다.

    남기지 않으면 /view·/market·signal_scoring이 야간 7시간을 통째로 보지
    못한다.
    """
    for highlight in result["highlights"]:
        item = items[highlight["index"]]
        codes = signal_codes(highlight["mentioned_stocks"])
        try:
            if prediction_log is not None:
                await prediction_log.record(
                    source=str(item.get("source") or ""),
                    title=highlight["title"],
                    sentiment=highlight["sentiment"],
                    impact=highlight["impact"],
                    codes=codes,
                    market=market,
                )
            if news_log is not None:
                await news_log.record(
                    source=str(item.get("source") or ""),
                    title=highlight["title"],
                    sentiment=highlight["sentiment"],
                    impact=highlight["impact"],
                    codes=codes,
                    market=market,
                    article_id=str(item.get("article_id") or ""),
                    occurred_at=publication_time_naive(
                        item.get("published_at"),
                        item.get("published_date") or None,
                    ),
                )
        except Exception as e:
            logger.error("[NIGHT] %s 야간 로그 기록 실패: %s", market, e)


async def _send_sections(
    bot: Bot,
    chat_id: str,
    header: str,
    sections: list[str],
) -> tuple[int, int]:
    max_body_length = NEWS_DIGEST_MESSAGE_MAX_CHARS - _DIGEST_HEADER_RESERVE
    chunks = chunk_message_items(
        sections,
        text_getter=lambda section: section,
        max_body_length=max_body_length,
        separator="\n\n",
    )
    sent = 0
    failed = 0
    for index, chunk in enumerate(chunks, start=1):
        text = f"{header} · {index}/{len(chunks)}\n\n" + "\n\n".join(chunk)
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            logger.error("[NIGHT] 야간 다이제스트 %d/%d 전송 실패: %s", index, len(chunks), e)
    return sent, failed


async def send_night_digest(app: Application) -> None:
    """큐에 쌓인 야간 기사를 시장별로 한 번씩 요약해 보내고 큐를 비운다."""
    async with _DIGEST_LOCK:
        await _send_night_digest(app)


@burst_job("야간 뉴스 다이제스트")
async def _send_night_digest(app: Application) -> None:
    queue: NightNewsQueue | None = app.bot_data.get("night_queue")
    analyzer: NightDigestAnalyzer | None = app.bot_data.get("night_digest_analyzer")
    if queue is None or analyzer is None:
        return
    opened_at, items = await queue.snapshot()
    if not items:
        return

    tracker: SentNewsTracker = app.bot_data["sent_tracker"]
    prediction_log: PredictionLog | None = app.bot_data.get("prediction_log")
    news_log: NewsLog | None = app.bot_data.get("news_log")
    window = _window_label(opened_at, now())

    sections: list[str] = []
    for market, market_items in group_by_market(items):
        result = await _analyze_market(analyzer, market, window, market_items)
        sections.append(format_market_section(market, market_items, result))
        if result is not None:
            await _log_highlights(market, market_items, result, prediction_log, news_log)

    header = (
        f"🌙 <b>야간 뉴스 다이제스트</b>\n{html.escape(window)} · 수집 {len(items)}건"
    )
    sent, failed = await _send_sections(app.bot, TELEGRAM_CHAT_ID, header, sections)
    if not sent:
        # 한 조각도 못 보냈다. 큐와 예약을 그대로 두고 다음 주기가 다시 시도한다.
        logger.error("[NIGHT] 야간 다이제스트를 보내지 못해 큐를 유지합니다(%d건).", len(items))
        return
    if failed:
        # 일부만 나갔다. 큐를 남기면 성공한 조각을 아침에 한 번 더 보내게 되므로
        # 비우고, 빠진 조각은 로그로만 남긴다.
        logger.error("[NIGHT] 야간 다이제스트 %d조각이 빠진 채 확정합니다.", failed)

    for item in items:
        await tracker.confirm(str(item.get("article_id") or ""))
    await tracker.persist()
    await queue.clear()
    logger.info("[NIGHT] 야간 다이제스트 전송 완료 · 기사 %d건 확정", len(items))


async def run_night_digest_job(app: Application) -> None:
    """예약 실행 경계. 받을 사람이 없으므로 실패를 여기서 삼킨다."""
    try:
        await send_night_digest(app)
    except Exception:
        logger.error("[NIGHT] 야간 다이제스트 예약 실행 실패", exc_info=True)
