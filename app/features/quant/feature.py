"""시세·자금흐름·섹터 정량 컨텍스트 기능 선언."""

from core.config import (
    QUANT_CACHE_TTL_MINUTES,
    QUANT_CONTEXT_ENABLED,
    QUANT_FAILURE_COOLDOWN_MINUTES,
    QUANT_HOT_RANK_ENABLED,
    QUANT_SECTOR_TOP_N,
)
from features.base import FeatureSpec
from stocks import QuoteService


def _install_services(app) -> None:
    app.bot_data["quote_service"] = QuoteService(
        enabled=QUANT_CONTEXT_ENABLED,
        cache_ttl_minutes=QUANT_CACHE_TTL_MINUTES,
        sector_top_n=QUANT_SECTOR_TOP_N,
        failure_cooldown_minutes=QUANT_FAILURE_COOLDOWN_MINUTES,
        hot_rank_enabled=QUANT_HOT_RANK_ENABLED,
    )

FEATURE = FeatureSpec(
    key="quant",
    label="정량 시장 데이터",
    requires=frozenset({"instruments"}),
    install_services=_install_services,
    summary="시세·자금흐름·섹터·상한가·용호방 데이터",
)
