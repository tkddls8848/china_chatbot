"""국가별 뉴스 감성 기능 선언."""

import asyncio

from core.clock import KST
from core.config import (
    MARKET_ANOMALY_COLLECTION_ENABLED,
    MARKET_ANOMALY_ENABLED,
    MARKET_ANOMALY_FILE,
    MARKET_ANOMALY_JOB_MINUTE,
    MARKET_ANOMALY_RETENTION_DAYS,
    MARKET_DIGEST_FILE,
    MARKET_DIGEST_RETENTION_DAYS,
    POLYMARKET_BASE_URL,
    POLYMARKET_CONSENSUS_FILE,
    POLYMARKET_ENABLED,
    POLYMARKET_RETENTION_DAYS,
    POLYMARKET_TIMEOUT,
)
from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.market_sentiment.handlers import cmd_market
from features.market_sentiment.overnight import capture_completed_overnight_windows
from features.market_sentiment.polymarket import PolymarketClient
from features.market_sentiment.snapshot import (
    SNAPSHOT_HOUR_SPEC,
    SNAPSHOT_MINUTE,
    capture_polymarket_snapshot,
)
from llm import build_market_digest_analyzer, build_overnight_tone_analyzer
from state import MarketDigestStore, OvernightToneStore, PolymarketConsensusStore


def _install_services(app) -> None:
    app.bot_data["market_digest_store"] = MarketDigestStore(
        MARKET_DIGEST_FILE,
        MARKET_DIGEST_RETENTION_DAYS,
    )
    app.bot_data["market_digest_analyzer"] = build_market_digest_analyzer()
    # 다이제스트는 /market 한 번에 수십 번 호출될 수 있다. 번역 파이프라인과
    # 같은 무료 할당량을 쓰므로 동시 호출을 1로 묶어 순서를 예측 가능하게 둔다.
    app.bot_data["market_digest_semaphore"] = asyncio.Semaphore(1)
    if MARKET_ANOMALY_ENABLED or MARKET_ANOMALY_COLLECTION_ENABLED:
        app.bot_data["overnight_tone_store"] = OvernightToneStore(
            MARKET_ANOMALY_FILE,
            MARKET_ANOMALY_RETENTION_DAYS,
        )
        app.bot_data["overnight_tone_analyzer"] = build_overnight_tone_analyzer()
    if POLYMARKET_ENABLED:
        # 뉴스 감성과 별개 축인 외부 참고선이다. 새 기능 키를 만들지 않고
        # 이 기능의 외부 소스로 붙인다.
        app.bot_data["polymarket_store"] = PolymarketConsensusStore(
            POLYMARKET_CONSENSUS_FILE,
            POLYMARKET_RETENTION_DAYS,
        )
        app.bot_data["polymarket_client"] = PolymarketClient(
            base_url=POLYMARKET_BASE_URL,
            timeout=POLYMARKET_TIMEOUT,
        )


def _install_jobs(scheduler, app) -> None:
    if POLYMARKET_ENABLED:
        scheduler.add_job(
            capture_polymarket_snapshot,
            trigger="cron",
            hour=SNAPSHOT_HOUR_SPEC,
            minute=SNAPSHOT_MINUTE,
            # 스케줄러 기본 타임존은 호스트를 따라간다. 하루 변화를 재려면 두
            # 스냅숏이 같은 시각이어야 하므로 여기서 KST로 고정한다.
            timezone=KST,
            args=[app],
            id="polymarket_snapshot",
            max_instances=1,
            coalesce=True,
        )
    if MARKET_ANOMALY_COLLECTION_ENABLED:
        # 고정 개장 시각 cron은 DST·반휴장을 다시 손으로 구현하게 된다. 30분마다
        # 깨워 거래소 캘린더가 "이미 끝난 창"만 돌려주게 한다.
        scheduler.add_job(
            capture_completed_overnight_windows,
            trigger="cron",
            minute=MARKET_ANOMALY_JOB_MINUTE,
            timezone=KST,
            args=[app],
            id="market_anomaly_capture",
            max_instances=1,
            coalesce=True,
        )


FEATURE = FeatureSpec(
    key="market_sentiment",
    label="국가별 뉴스 감성",
    requires=frozenset({"news"}),
    commands=(
        CommandSpec("market", "국가별 뉴스 감성", cmd_market, usage="[일수]"),
    ),
    menus=(
        MenuSpec("📊 국가별 감성", "nav:market", 0, "📊 감성", 0),
    ),
    install_services=_install_services,
    install_jobs=_install_jobs,
    data_files=(
        "data/market_sentiment/daily_digest.json",
        "data/market_sentiment/overnight_tone.json",
        "data/market_sentiment/polymarket_consensus.json",
    ),
)
