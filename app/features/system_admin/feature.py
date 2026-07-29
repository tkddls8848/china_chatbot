"""시작·도움말·시스템 제어 기능 선언."""

import logging

from core.config import OLLAMA_GPU_ON_VALUE, OLLAMA_NUM_GPU
from core.system_control import SystemControlManager
from features.base import CommandSpec, FeatureSpec, MenuSpec
from features.system_admin.handlers import cmd_help, cmd_start, cmd_system

logger = logging.getLogger(__name__)


def _install_services(app) -> None:
    system = SystemControlManager(
        default_num_gpu=OLLAMA_NUM_GPU,
        gpu_on_value=OLLAMA_GPU_ON_VALUE,
    )
    for key in ("translator", "market_view_analyzer", "briefing_writer"):
        consumer = app.bot_data.get(key)
        if consumer is not None:
            system.register_consumer(consumer.set_num_gpu)
    app.bot_data["system_control"] = system
    logger.info(
        "[System] GPU 가속 초기 상태: %s (num_gpu=%d)",
        "켜짐" if system.gpu_enabled else "꺼짐(CPU)",
        system.num_gpu,
    )


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
    install_services=_install_services,
)
