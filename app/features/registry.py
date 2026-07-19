"""활성 기능 검증과 텔레그램·스케줄러 기여점 조립."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from core.access import restricted
from features.base import FeatureSpec
from handlers.commands import callback_handler
from handlers.navigation import handle_menu_text


class FeatureConfigurationError(ValueError):
    pass


class FeatureRegistry:
    def __init__(
        self,
        specs: Iterable[FeatureSpec],
        enabled_keys: Iterable[str],
    ):
        all_specs = list(specs)
        by_key = {spec.key: spec for spec in all_specs}
        if len(by_key) != len(all_specs):
            duplicates = [
                key
                for key, count in Counter(spec.key for spec in all_specs).items()
                if count > 1
            ]
            raise FeatureConfigurationError(
                f"중복 기능 키: {', '.join(sorted(duplicates))}"
            )

        requested = {str(key).strip() for key in enabled_keys if str(key).strip()}
        unknown = requested - set(by_key)
        if unknown:
            raise FeatureConfigurationError(
                f"알 수 없는 기능: {', '.join(sorted(unknown))}"
            )

        requested_specs = [spec for spec in all_specs if spec.key in requested]
        missing_dependencies = {
            spec.key: sorted(spec.requires - requested)
            for spec in requested_specs
            if spec.requires - requested
        }
        if missing_dependencies:
            details = "; ".join(
                f"{key} -> {', '.join(missing)}"
                for key, missing in sorted(missing_dependencies.items())
            )
            raise FeatureConfigurationError(f"기능 의존성 누락: {details}")

        enabled_specs: list[FeatureSpec] = []
        installed_keys: set[str] = set()
        pending = list(requested_specs)
        while pending:
            ready = [
                spec
                for spec in pending
                if spec.requires <= installed_keys
            ]
            if not ready:
                cycle = ", ".join(sorted(spec.key for spec in pending))
                raise FeatureConfigurationError(
                    f"기능 의존성 순환: {cycle}"
                )
            for spec in ready:
                enabled_specs.append(spec)
                installed_keys.add(spec.key)
                pending.remove(spec)

        command_names = [
            command.name
            for spec in enabled_specs
            for command in spec.commands
        ]
        duplicate_commands = [
            name
            for name, count in Counter(command_names).items()
            if count > 1
        ]
        if duplicate_commands:
            raise FeatureConfigurationError(
                f"중복 텔레그램 명령어: {', '.join(sorted(duplicate_commands))}"
            )

        data_owners: dict[str, list[str]] = {}
        for spec in all_specs:
            for path in spec.data_files:
                data_owners.setdefault(path, []).append(spec.key)
        duplicate_data = {
            path: owners
            for path, owners in data_owners.items()
            if len(owners) > 1
        }
        if duplicate_data:
            details = "; ".join(
                f"{path} -> {', '.join(owners)}"
                for path, owners in sorted(duplicate_data.items())
            )
            raise FeatureConfigurationError(f"데이터 소유권 중복: {details}")

        self._all_specs = tuple(all_specs)
        self._enabled_specs = tuple(enabled_specs)
        self._enabled_keys = frozenset(requested)

    @property
    def enabled_keys(self) -> frozenset[str]:
        return self._enabled_keys

    @property
    def enabled_specs(self) -> tuple[FeatureSpec, ...]:
        return self._enabled_specs

    def is_enabled(self, key: str) -> bool:
        return key in self._enabled_keys

    def install_telegram_handlers(self, app: Application) -> None:
        for feature in self._enabled_specs:
            for command in feature.commands:
                app.add_handler(
                    CommandHandler(command.name, restricted(command.handler))
                )
        app.add_handler(CallbackQueryHandler(restricted(callback_handler)))
        app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                restricted(handle_menu_text, show_status=False),
            )
        )

    def install_services(self, app: Application) -> None:
        for feature in self._enabled_specs:
            if feature.install_services is not None:
                feature.install_services(app)

    def install_jobs(self, scheduler, app: Application) -> None:
        for feature in self._enabled_specs:
            if feature.install_jobs is not None:
                feature.install_jobs(scheduler, app)

    def telegram_commands(self) -> list[BotCommand]:
        return [
            BotCommand(command.name, command.description)
            for feature in self._enabled_specs
            for command in feature.commands
        ]

    def menu_specs(self):
        return [
            menu
            for feature in self._enabled_specs
            for menu in feature.menus
        ]

    def help_text(self) -> str:
        lines = ["<b>명령어 안내</b>", ""]
        for feature in self._enabled_specs:
            for command in feature.commands:
                lines.append(f"/{command.name} — {command.description}")
        return "\n".join(lines)

    def catalog_lines(self) -> list[str]:
        lines = []
        for feature in self._all_specs:
            enabled = feature.key in self._enabled_keys
            state = "활성" if enabled else "비활성"
            commands = ", ".join(f"/{item.name}" for item in feature.commands)
            detail = f" · {commands}" if commands else ""
            dependencies = (
                f" · 의존: {', '.join(sorted(feature.requires))}"
                if feature.requires
                else ""
            )
            schedule = " · 스케줄" if feature.install_jobs is not None else ""
            data = (
                f" · 데이터: {', '.join(feature.data_files)}"
                if feature.data_files
                else ""
            )
            lines.append(
                f"{feature.key} ({feature.label}): "
                f"{state}{detail}{dependencies}{schedule}{data}"
            )
        return lines
