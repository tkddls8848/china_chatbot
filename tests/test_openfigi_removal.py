"""제거된 종목 DB 보조 경로의 회귀 테스트."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")


def test_legacy_yahoo_enrichment_module_is_removed():
    assert not (ROOT / "app" / "stocks" / "enrichment.py").exists()


def test_stock_database_config_has_no_openfigi_api_key():
    from core import config

    assert not hasattr(config, "OPENFIGI_API_KEY")
