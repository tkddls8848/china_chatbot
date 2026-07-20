"""레거시 평면 data/ 배치의 기능별 디렉토리 이전 검증."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from core import config
from core.data_layout import _default_pairs, migrate_legacy_data_files


def test_moves_legacy_file_to_feature_directory(tmp_path):
    legacy = tmp_path / "watchlist.json"
    legacy.write_text('{"600519": "Kweichow"}', encoding="utf-8")
    current = tmp_path / "watchlist" / "watchlist.json"

    moved = migrate_legacy_data_files([(legacy, current)])

    assert moved == [current]
    assert not legacy.exists()
    assert current.read_text(encoding="utf-8") == '{"600519": "Kweichow"}'


def test_keeps_existing_new_file_and_legacy_untouched(tmp_path):
    legacy = tmp_path / "watchlist.json"
    legacy.write_text("old", encoding="utf-8")
    current = tmp_path / "watchlist" / "watchlist.json"
    current.parent.mkdir(parents=True)
    current.write_text("new", encoding="utf-8")

    moved = migrate_legacy_data_files([(legacy, current)])

    assert moved == []
    assert legacy.read_text(encoding="utf-8") == "old"
    assert current.read_text(encoding="utf-8") == "new"


def test_noop_when_no_legacy_files(tmp_path):
    current = tmp_path / "news" / "news_log.json"
    assert migrate_legacy_data_files([(tmp_path / "news_log.json", current)]) == []
    assert not current.exists()


def test_default_pairs_cover_all_config_data_files():
    pairs = dict(_default_pairs())
    expected_new_paths = {
        config.SENT_IDS_FILE,
        config.NEWS_LOG_FILE,
        config.WATCHLIST_FILE,
        config.WATCHLIST_EVENTS_FILE,
        config.STOCK_DB_FILE,
        config.PREDICTION_LOG_FILE,
        config.RESEARCH_STATE_FILE,
    }
    assert set(pairs.values()) == expected_new_paths
    # 레거시 위치는 data/ 바로 아래 같은 파일명이어야 한다.
    for legacy, current in pairs.items():
        assert legacy == config.DATA_DIR / current.name


def test_config_paths_follow_feature_directory_layout():
    assert config.SENT_IDS_FILE.parent == config.DATA_DIR / "news"
    assert config.NEWS_LOG_FILE.parent == config.DATA_DIR / "news"
    assert config.WATCHLIST_FILE.parent == config.DATA_DIR / "watchlist"
    assert config.WATCHLIST_EVENTS_FILE.parent == config.DATA_DIR / "watchlist"
    assert config.STOCK_DB_FILE.parent == config.DATA_DIR / "instruments"
    assert config.PREDICTION_LOG_FILE.parent == config.DATA_DIR / "signal_scoring"
    assert config.RESEARCH_STATE_FILE.parent == config.DATA_DIR / "research"
    assert config.RUNTIME_LOCK_FILE.parent == config.DATA_DIR / "runtime"
