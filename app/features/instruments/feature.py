"""종목 마스터 데이터 기능 선언."""

from core.config import STOCK_DB_ENABLED, STOCK_DB_FILE
from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.instruments.handlers import cmd_stockdb
from news.pipeline import refresh_stock_db
from stocks import StockDatabase


def _install_services(app) -> None:
    stock_db = StockDatabase(cache_file=STOCK_DB_FILE, enabled=STOCK_DB_ENABLED)
    stock_db.load_or_build()
    app.bot_data["stock_db"] = stock_db


def _install_jobs(scheduler, app) -> None:
    scheduler.add_job(
        refresh_stock_db,
        trigger="cron",
        hour=8,
        minute=30,
        args=[app.bot_data["stock_db"]],
        id="refresh_stock_db",
    )


FEATURE = FeatureSpec(
    key="instruments",
    label="종목 데이터베이스",
    commands=(CommandSpec("stockdb", "종목 DB 갱신", cmd_stockdb),),
    menus=(
        MenuSpec("🗂 종목 DB 갱신", "nav:stockdb", 3),
    ),
    install_services=_install_services,
    install_jobs=_install_jobs,
    data_files=("data/stock_db.json",),
    summary="국가별 종목 코드·종목명·검색 후보군",
)
