"""뉴스 수집·번역·전송 기능 선언."""

import asyncio
from core.clock import now

from core.config import (
    NEWS_GLOBAL_SOURCE_KEYS,
    NEWS_LOG_FILE,
    NEWS_LOG_RETENTION_DAYS,
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
from llm import build_translation_service
from news import NewsSourceRegistry, build_source_specs
from news.pipeline import fetch_all
from state import NewsLog, SentNewsTracker


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


def _install_jobs(scheduler, app) -> None:
    scheduler.add_job(
        fetch_all,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        args=[app],
        next_run_time=now(),
        id="news_digest",
        max_instances=1,
        coalesce=True,
    )


FEATURE = FeatureSpec(
    key="news",
    label="뉴스 수집·다이제스트",
    requires=frozenset({"watchlist"}),
    install_services=_install_services,
    install_jobs=_install_jobs,
    data_files=("data/news/sent_ids.json", "data/news/news_log.json"),
)
