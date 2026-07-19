"""종목 감성 뷰와 신호 성과 기능 선언."""

from core.config import PREDICTION_LOG_FILE
from features.base import CommandSpec, FeatureSpec, MenuSpec
from handlers.commands import cmd_score, cmd_view
from state import PredictionLog


def _install_services(app) -> None:
    app.bot_data["prediction_log"] = PredictionLog(PREDICTION_LOG_FILE)

FEATURE = FeatureSpec(
    key="signal_scoring",
    label="감성 신호 성과",
    requires=frozenset({"news", "watchlist", "instruments"}),
    commands=(
        CommandSpec("view", "종목 감성 보기", cmd_view),
        CommandSpec("score", "신호 성과 채점", cmd_score),
    ),
    menus=(
        MenuSpec("📈 신호 성과", "nav:score", 2, "📈 성과", 1),
    ),
    install_services=_install_services,
    data_files=("data/prediction_log.jsonl",),
    summary="뉴스 감성의 종목별 집계와 실제 가격 방향 채점",
)
