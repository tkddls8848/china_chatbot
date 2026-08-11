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
        CommandSpec(
            "system",
            "시스템 상태",
            cmd_system,
            usage="[features|polymarket]",
        ),
        CommandSpec("help", "명령어 안내", cmd_help),
    ),
    menus=(
        # 하단 고정 메뉴는 리서치·브리핑과 같은 줄(1행)에 둔다.
        MenuSpec("⚙️ 시스템", "nav:system", 2, "⚙️ 관리", 1),
        MenuSpec("❔ 도움말", "nav:help", 3),
    ),
)
