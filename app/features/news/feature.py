"""뉴스 수집·번역·전송 기능 선언."""

import asyncio
import logging
from core.clock import now

from core.config import (
    NEWS_GLOBAL_SOURCE_KEYS,
    NEWS_LOG_FILE,
    NEWS_LOG_RETENTION_DAYS,
    NEWS_NIGHT_DIGEST_ENABLED,
    NEWS_NIGHT_END_HOUR,
    NEWS_NIGHT_QUEUE_FILE,
    NEWS_NIGHT_QUEUE_MAX_ITEMS,
    NEWS_NIGHT_QUEUE_PER_SOURCE_LIMIT,
    NEWS_RSS_FEEDS,
    NEWS_SOURCE_COOLDOWN_MINUTES,
    NEWS_SOURCE_FAILURE_THRESHOLD,
    NEWS_SOURCE_MARKETS,
    SCHEDULER_INTERVAL_MINUTES,
    SENT_IDS_FILE,
    SENT_NEWS_RETENTION_DAYS,
    TRANSLATION_CONCURRENCY,
)
from features.base import FeatureSpec
from llm import build_night_digest_analyzer, build_translation_service
from news import NewsSourceRegistry, build_source_specs
from news.night import (
    collect_night_articles,
    is_night_window,
    run_night_digest_job,
    send_night_digest,
)
from news.pipeline import fetch_all
from state import NewsLog, NightNewsQueue, SentNewsTracker

logger = logging.getLogger(__name__)


def _install_services(app) -> None:
    app.bot_data["sent_tracker"] = SentNewsTracker(
        SENT_IDS_FILE,
        SENT_NEWS_RETENTION_DAYS,
    )
    app.bot_data["news_registry"] = NewsSourceRegistry(
        build_source_specs(
            NEWS_GLOBAL_SOURCE_KEYS,
            NEWS_RSS_FEEDS,
            NEWS_SOURCE_MARKETS,
        ),
        failure_threshold=NEWS_SOURCE_FAILURE_THRESHOLD,
        cooldown_minutes=NEWS_SOURCE_COOLDOWN_MINUTES,
    )
    app.bot_data["news_log"] = NewsLog(
        NEWS_LOG_FILE,
        NEWS_LOG_RETENTION_DAYS,
    )
    app.bot_data["translator"] = build_translation_service()
    app.bot_data["translate_semaphore"] = asyncio.Semaphore(
        TRANSLATION_CONCURRENCY
    )
    app.bot_data["global_news_cursor"] = 0
    if NEWS_NIGHT_DIGEST_ENABLED:
        app.bot_data["night_queue"] = NightNewsQueue(
            NEWS_NIGHT_QUEUE_FILE,
            per_source_limit=NEWS_NIGHT_QUEUE_PER_SOURCE_LIMIT,
            max_items=NEWS_NIGHT_QUEUE_MAX_ITEMS,
        )
        app.bot_data["night_digest_analyzer"] = build_night_digest_analyzer()


async def run_news_cycle(app) -> None:
    """주기마다 야간 수집과 주간 번역 중 하나를 고른다.

    야간에는 번역하지 않고 큐에만 담는다. 주간 첫 주기는 밤새 쌓인 큐를 먼저
    비운다 — 07시 job이 실패했거나 그때 봇이 떠 있지 않았어도 야간 기사가
    번역되지 않은 채 사라지지 않게 한다.
    """
    if NEWS_NIGHT_DIGEST_ENABLED and is_night_window():
        await collect_night_articles(app)
        return
    if NEWS_NIGHT_DIGEST_ENABLED:
        try:
            await send_night_digest(app)
        except Exception:
            logger.error("[NIGHT] 남은 야간 큐 전송 실패", exc_info=True)
    await fetch_all(app)


def _install_jobs(scheduler, app) -> None:
    scheduler.add_job(
        run_news_cycle,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        args=[app],
        next_run_time=now(),
        id="news_digest",
        max_instances=1,
        coalesce=True,
    )
    if NEWS_NIGHT_DIGEST_ENABLED:
        scheduler.add_job(
            run_night_digest_job,
            trigger="cron",
            hour=NEWS_NIGHT_END_HOUR,
            minute=0,
            args=[app],
            id="night_digest",
            max_instances=1,
            coalesce=True,
        )


FEATURE = FeatureSpec(
    key="news",
    label="뉴스 수집·다이제스트",
    requires=frozenset({"watchlist"}),
    install_services=_install_services,
    install_jobs=_install_jobs,
    data_files=(
        "data/news/sent_ids.json",
        "data/news/news_log.json",
        "data/news/night_queue.json",
    ),
)
