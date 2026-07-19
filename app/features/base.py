"""기능 모듈이 애플리케이션에 제공하는 공개 선언 계약."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

CommandHandlerFunc = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[None],
]
JobInstaller = Callable[[Any, Any], None]
ServiceInstaller = Callable[[Any], None]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: CommandHandlerFunc


@dataclass(frozen=True)
class MenuSpec:
    label: str
    callback_data: str
    row: int
    persistent_label: str = ""
    persistent_row: int = 0


@dataclass(frozen=True)
class FeatureSpec:
    """한 기능의 의존성·진입점·소유 자원을 한곳에 선언한다."""

    key: str
    label: str
    requires: frozenset[str] = frozenset()
    commands: tuple[CommandSpec, ...] = ()
    menus: tuple[MenuSpec, ...] = ()
    install_services: ServiceInstaller | None = None
    install_jobs: JobInstaller | None = None
    data_files: tuple[str, ...] = ()
    prompts: tuple[str, ...] = ()
    summary: str = ""
