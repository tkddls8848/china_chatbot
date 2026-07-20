"""국가별 뉴스 감성 기능 선언."""

from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.market_sentiment.handlers import cmd_market

FEATURE = FeatureSpec(
    key="market_sentiment",
    label="국가별 뉴스 감성",
    requires=frozenset({"news"}),
    commands=(CommandSpec("market", "국가별 뉴스 감성", cmd_market),),
    menus=(
        MenuSpec("📊 국가별 감성", "nav:market", 0, "📊 감성", 0),
    ),
    summary="날짜별 뉴스 백필·시장 감성 집계·시계열 차트",
)
