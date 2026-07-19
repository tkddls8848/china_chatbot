"""기능 카탈로그의 단일 조립 지점."""

from features.briefing.feature import FEATURE as BRIEFING
from features.instruments.feature import FEATURE as INSTRUMENTS
from features.market_sentiment.feature import FEATURE as MARKET_SENTIMENT
from features.news.feature import FEATURE as NEWS
from features.quant.feature import FEATURE as QUANT
from features.registry import FeatureRegistry
from features.research.feature import FEATURE as RESEARCH
from features.signal_scoring.feature import FEATURE as SIGNAL_SCORING
from features.system_admin.feature import FEATURE as SYSTEM_ADMIN
from features.watchlist.feature import FEATURE as WATCHLIST

ALL_FEATURES = (
    INSTRUMENTS,
    QUANT,
    WATCHLIST,
    NEWS,
    MARKET_SENTIMENT,
    RESEARCH,
    BRIEFING,
    SIGNAL_SCORING,
    SYSTEM_ADMIN,
)


def build_feature_registry(enabled_keys) -> FeatureRegistry:
    return FeatureRegistry(ALL_FEATURES, enabled_keys)


__all__ = ["ALL_FEATURES", "FeatureRegistry", "build_feature_registry"]
