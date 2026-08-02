"""시작·도움말·시스템 제어 기능 선언."""

import logging

from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.system_admin.handlers import cmd_help, cmd_start, cmd_system

logger = logging.getLogger(__name__)


FEATURE = FeatureSpec(
    key="system_admin",
    label="시스템 관리",
    commands=(
        CommandSpec("start", "사용 안내", cmd_start),
        CommandSpec("system", "시스템 상태", cmd_system),
        CommandSpec("help", "명령어 안내", cmd_help),
    ),
    menus=(
        MenuSpec("⚙️ 시스템", "nav:system", 2, "⚙️ 관리", 2),
        MenuSpec("❔ 도움말", "nav:help", 3),
    ),
)
