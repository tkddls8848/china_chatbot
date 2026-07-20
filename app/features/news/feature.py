"""뉴스 수집·번역·전송 기능 선언."""

import asyncio
from datetime import datetime

from core.config import (
    NEWS_GLOBAL_SOURCE_KEYS,
    NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS,
    NEWS_LOG_FILE,
    NEWS_LOG_RETENTION_DAYS,
    NEWS_RSS_FEEDS,
    NEWS_SOURCE_COOLDOWN_MINUTES,
    NEWS_SOURCE_FAILURE_THRESHOLD,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_GPU,
    PROMPT_DIR,
    SCHEDULER_INTERVAL_MINUTES,
    SENT_IDS_FILE,
    SENT_NEWS_RETENTION_DAYS,
    TRANSLATION_CONCURRENCY,
    TRANSLATION_ENABLED,
    TRANSLATION_MODEL,
    TRANSLATION_NUM_PREDICT,
    TRANSLATION_TIMEOUT,
)
from features.base import FeatureSpec
from llm import TranslationService
from news import NewsSourceRegistry, build_source_specs
from news.pipeline import fetch_all
from state import NewsLog, SentNewsTracker


def _install_services(app) -> None:
    app.bot_data["sent_tracker"] = SentNewsTracker(
        SENT_IDS_FILE,
        SENT_NEWS_RETENTION_DAYS,
    )
    app.bot_data["news_registry"] = NewsSourceRegistry(
        build_source_specs(NEWS_GLOBAL_SOURCE_KEYS, NEWS_RSS_FEEDS),
        failure_threshold=NEWS_SOURCE_FAILURE_THRESHOLD,
        cooldown_minutes=NEWS_SOURCE_COOLDOWN_MINUTES,
    )
    app.bot_data["news_log"] = NewsLog(
        NEWS_LOG_FILE,
        NEWS_LOG_RETENTION_DAYS,
    )
    app.bot_data["translator"] = TranslationService(
        base_url=OLLAMA_BASE_URL,
        model=TRANSLATION_MODEL,
        enabled=TRANSLATION_ENABLED,
        timeout=TRANSLATION_TIMEOUT,
        prompt_dir=PROMPT_DIR,
        num_gpu=OLLAMA_NUM_GPU,
        num_predict=TRANSLATION_NUM_PREDICT,
        brief_content_limit=NEWS_GLOBAL_TRANSLATED_CONTENT_MAX_CHARS,
    )
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
        next_run_time=datetime.now(),
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
    prompts=("prompts/futu_ko.txt", "prompts/global_ko.txt"),
    summary="Futu·Sina·Google News·RSS 수집, 번역, 날짜 필터와 전송",
)
