"""종목 감성 뷰 기능 선언."""

from core.config import PREDICTION_LOG_FILE
from features.base import CommandSpec, FeatureSpec
from features.signal_scoring.handlers import cmd_view
from state import PredictionLog


def _install_services(app) -> None:
    app.bot_data["prediction_log"] = PredictionLog(PREDICTION_LOG_FILE)

FEATURE = FeatureSpec(
    key="signal_scoring",
    label="종목 감성 뷰",
    requires=frozenset({"news", "watchlist", "instruments"}),
    commands=(
        CommandSpec("view", "종목 감성 보기", cmd_view, usage="[종목코드]"),
    ),
    install_services=_install_services,
    data_files=("data/signal_scoring/prediction_log.jsonl",),
)
