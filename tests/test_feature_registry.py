import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from features import ALL_FEATURES, build_feature_registry
from features.registry import FeatureConfigurationError
from handlers.navigation import main_menu, persistent_menu


EXPECTED_FEATURES = {
    "instruments",
    "quant",
    "watchlist",
    "news",
    "market_sentiment",
    "research",
    "briefing",
    "signal_scoring",
    "system_admin",
}


def test_feature_catalog_declares_every_supported_capability():
    assert {feature.key for feature in ALL_FEATURES} == EXPECTED_FEATURES
    assert "em" not in {feature.key for feature in ALL_FEATURES}


def test_full_feature_set_has_unique_commands_and_valid_dependencies():
    registry = build_feature_registry(EXPECTED_FEATURES)

    command_names = [
        command.command
        for command in registry.telegram_commands()
    ]

    assert len(command_names) == len(set(command_names))
    assert {"market", "research", "briefing", "score", "system"} <= set(
        command_names
    )


def test_registry_rejects_missing_feature_dependency():
    with pytest.raises(FeatureConfigurationError, match="기능 의존성 누락"):
        build_feature_registry({"market_sentiment"})


def test_registry_rejects_unknown_feature():
    with pytest.raises(FeatureConfigurationError, match="알 수 없는 기능"):
        build_feature_registry({"unknown"})


def test_disabled_features_are_removed_from_both_menus():
    enabled = frozenset({"instruments", "system_admin"})

    inline_labels = {
        button.text
        for row in main_menu(enabled).inline_keyboard
        for button in row
    }
    persistent_labels = {
        button.text
        for row in persistent_menu(enabled).keyboard
        for button in row
    }

    assert inline_labels == {"🗂 종목 DB 갱신", "❔ 도움말", "⚙️ 시스템"}
    assert persistent_labels == {"🏠 홈", "⚙️ 관리"}


def test_catalog_reports_enabled_and_disabled_states():
    registry = build_feature_registry({"instruments", "system_admin"})
    lines = registry.catalog_lines()

    assert any(line.startswith("instruments ") and ": 활성" in line for line in lines)
    assert any(line.startswith("news ") and ": 비활성" in line for line in lines)


def test_disabled_features_do_not_initialize_their_services():
    registry = build_feature_registry({"system_admin"})
    app = SimpleNamespace(bot_data={})

    registry.install_services(app)

    assert "system_control" in app.bot_data
    assert "stock_db" not in app.bot_data
    assert "translator" not in app.bot_data
    assert "market_view_analyzer" not in app.bot_data


def test_generated_help_contains_only_enabled_commands():
    registry = build_feature_registry({"system_admin"})

    text = registry.help_text()

    assert "/system" in text
    assert "/help" in text
    assert "/research" not in text
    assert "/market" not in text
