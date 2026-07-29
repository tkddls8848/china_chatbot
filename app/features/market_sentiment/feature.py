"""국가별 뉴스 감성 기능 선언."""

from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.market_sentiment.handlers import cmd_market

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
)
