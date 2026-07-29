from dataclasses import replace
from types import SimpleNamespace

import pytest

from features import ALL_FEATURES, build_feature_registry
from features.base import FeatureSpec, MenuSpec
from features.registry import FeatureConfigurationError, FeatureRegistry
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
    "web_admin",
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


def test_service_installation_preserves_catalog_order_and_wires_gpu_consumers():
    installed = []
    consumers = {}
    service_keys = {
        "news": "translator",
        "research": "market_view_analyzer",
        "briefing": "briefing_writer",
    }

    class Consumer:
        num_gpu = None

        def set_num_gpu(self, num_gpu):
            self.num_gpu = num_gpu

    def installer(spec):
        original = spec.install_services

        def install(app):
            installed.append(spec.key)
            service_key = service_keys.get(spec.key)
            if service_key is not None:
                consumer = Consumer()
                consumers[service_key] = consumer
                app.bot_data[service_key] = consumer
            elif spec.key == "system_admin":
                original(app)

        return install

    specs = tuple(
        replace(spec, install_services=installer(spec))
        for spec in ALL_FEATURES
    )
    registry = FeatureRegistry(specs, EXPECTED_FEATURES)
    app = SimpleNamespace(bot_data={})

    registry.install_services(app)

    assert installed == [spec.key for spec in ALL_FEATURES]
    app.bot_data["system_control"].set_gpu_layers(7)
    assert {consumer.num_gpu for consumer in consumers.values()} == {7}


def test_registry_rejects_missing_feature_dependency():
    with pytest.raises(FeatureConfigurationError, match="기능 의존성 누락"):
        build_feature_registry({"market_sentiment"})


def test_registry_rejects_unknown_feature():
    with pytest.raises(FeatureConfigurationError, match="알 수 없는 기능"):
        build_feature_registry({"unknown"})


def test_disabled_features_are_removed_from_both_menus():
    enabled = frozenset({"instruments", "system_admin"})
    registry = build_feature_registry(enabled)

    inline_labels = {
        button.text
        for row in main_menu(registry).inline_keyboard
        for button in row
    }
    persistent_labels = {
        button.text
        for row in persistent_menu(registry).keyboard
        for button in row
    }

    assert inline_labels == {"🗂 종목 DB 갱신", "❔ 도움말", "⚙️ 시스템"}
    assert persistent_labels == {"🏠 홈", "⚙️ 관리"}


def test_registry_resolves_menu_ownership_and_persistent_labels():
    registry = build_feature_registry(EXPECTED_FEATURES)

    assert registry.menu_owner("nav:market") == "market_sentiment"
    assert registry.menu_owner("nav:market:30") == "market_sentiment"
    assert registry.menu_owner("nav:marketplace") is None
    assert registry.persistent_callback("📊 감성") == "nav:market"
    assert registry.persistent_callback("없는 메뉴") is None


def test_registry_rejects_duplicate_menu_callbacks():
    specs = (
        FeatureSpec(
            key="alpha",
            label="알파",
            menus=(MenuSpec("알파", "nav:shared", 0),),
        ),
        FeatureSpec(
            key="beta",
            label="베타",
            menus=(MenuSpec("베타", "nav:shared", 1),),
        ),
    )

    with pytest.raises(
        FeatureConfigurationError,
        match="중복 메뉴 callback_data",
    ):
        FeatureRegistry(specs, {"alpha", "beta"})


def test_registry_rejects_duplicate_persistent_labels():
    specs = (
        FeatureSpec(
            key="alpha",
            label="알파",
            menus=(MenuSpec("알파", "nav:alpha", 0, "공통", 0),),
        ),
        FeatureSpec(
            key="beta",
            label="베타",
            menus=(MenuSpec("베타", "nav:beta", 1, "공통", 1),),
        ),
    )

    with pytest.raises(FeatureConfigurationError, match="중복 하단 메뉴 라벨"):
        FeatureRegistry(specs, {"alpha", "beta"})


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


def test_generated_help_includes_command_usage_and_code_examples():
    registry = build_feature_registry(EXPECTED_FEATURES)

    text = registry.help_text()

    assert "/market [일수]" in text
    assert "/research show|set|run|clear" in text
    assert "/briefing morning|evening|scorecard" in text
    assert "/score — 신호 성과 채점" in text
    assert "KR:KOSPI:005930" in text
