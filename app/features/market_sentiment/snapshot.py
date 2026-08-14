"""08:35 KST Polymarket 스냅숏 job.

새 기능이 아니라 `market_sentiment`가 읽는 외부 소스 하나다. 그래서 실패가
바깥으로 새면 안 된다 — 이 job은 **어떤 예외도 밖으로 내보내지 않는다.**
Gamma가 죽거나 규칙이 아무 계약도 고르지 못한 날은 그날 스냅숏이 없는 것으로
끝나고, 뉴스 주기·브리핑·`/market`은 평소대로 돈다. 빠진 날은 `daily_changes`가
알아서 건너뛴다(앞 값으로 채우지 않는다).

시각을 08:35로 고정하는 이유는 비교 가능성이다. 하루 변화를 재려면 두 스냅숏이
같은 시각이어야 한다. 봇이 내려가 있어서 놓친 날을 나중에 따라잡지 않는 것도
같은 이유다 — 오후에 찍은 값은 다른 날들과 같은 축에 놓을 수 없다.
"""

from __future__ import annotations

import asyncio
import logging

from core.clock import now, today
from core.config import (
    POLYMARKET_MAX_HORIZON_DAYS,
    POLYMARKET_MAX_SPREAD,
    POLYMARKET_MIN_LIQUIDITY,
    POLYMARKET_MIN_VOLUME,
)
from features.market_sentiment.polymarket_rules import select_contracts

logger = logging.getLogger(__name__)

# APScheduler cron은 스케줄러 타임존을 따르므로 job 등록 시 KST를 명시한다.
SNAPSHOT_HOUR = 8
SNAPSHOT_MINUTE = 35


async def capture_polymarket_snapshot(app) -> None:
    """게이트를 통과한 계약의 Yes 확률을 하루치로 적는다."""
    client = app.bot_data.get("polymarket_client")
    store = app.bot_data.get("polymarket_store")
    if client is None or store is None:
        return

    try:
        contracts = await asyncio.to_thread(
            client.fetch_open_contracts,
            min_volume=POLYMARKET_MIN_VOLUME,
            min_liquidity=POLYMARKET_MIN_LIQUIDITY,
            max_horizon_days=POLYMARKET_MAX_HORIZON_DAYS,
        )
        selected, rejected = select_contracts(
            contracts,
            min_volume=POLYMARKET_MIN_VOLUME,
            min_liquidity=POLYMARKET_MIN_LIQUIDITY,
            max_spread=POLYMARKET_MAX_SPREAD,
            max_horizon_days=POLYMARKET_MAX_HORIZON_DAYS,
            moment=now(),
        )
        if not selected:
            logger.warning(
                "[POLYMARKET] 게이트를 통과한 계약이 없어 스냅숏을 남기지 않습니다. 사유=%s",
                dict(sorted(rejected.items())),
            )
            return
        stored = await store.put_snapshot(
            today(),
            {
                item.contract.condition_id: {
                    "price": item.contract.yes_price,
                    "spread": item.contract.spread,
                    "theme": item.theme,
                    "polarity": item.polarity,
                    "event_id": item.contract.event_id,
                    "question": item.contract.question,
                }
                for item in selected
            },
        )
        if not stored:
            logger.info("[POLYMARKET] 오늘 스냅숏이 이미 있어 건너뜁니다.")
            return
        logger.info(
            "[POLYMARKET] 스냅숏 저장: 계약=%d, theme=%s, 탈락=%s",
            len(selected),
            sorted({item.theme for item in selected}),
            dict(sorted(rejected.items())),
        )
    except Exception:
        # 외부 소스 하나의 실패가 다른 스케줄 작업으로 번지지 않게 여기서 끝낸다.
        logger.exception("[POLYMARKET] 스냅숏 수집 실패")
