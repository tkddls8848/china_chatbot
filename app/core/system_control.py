"""런타임에 텔레그램으로 제어 가능한 시스템 설정.

현재는 로컬 Ollama의 GPU 사용(num_gpu)을 제어한다. 클라우드 VM에 올린 뒤
텔레그램을 시스템 제어 대시보드로 쓰기 위한 단일 진입점이며, 이후 다른
런타임 설정도 이 매니저로 확장한다.

설정의 원본은 `.env`(OLLAMA_NUM_GPU 등)다. 여기서의 변경은 세션 한정으로,
영속화하지 않으며 재시작하면 `.env` 값으로 되돌아간다.

Ollama의 num_gpu 의미:
  - -1 → GPU 자동 (가능한 레이어를 전부 오프로딩)
  -  0 → CPU 전용
  -  N>0 → GPU에 올릴 레이어 수 (모델 레이어 수로 클램프됨)
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# GPU "켜짐"으로 토글할 때 사용할 기본값. -1(자동)이 가장 무난하다.
DEFAULT_GPU_ON_VALUE = -1


def _normalize(value: Any) -> int:
    """num_gpu 값을 정규화한다. 허용 범위는 -1 이상(-1=자동, 0=CPU, N=레이어)."""
    try:
        return max(-1, int(value))
    except (TypeError, ValueError):
        return 0


class SystemControlManager:
    """런타임 시스템 설정을 세션 한정으로 보유하고 소비자(서비스)에 전파한다."""

    def __init__(
        self,
        default_num_gpu: int,
        gpu_on_value: int = DEFAULT_GPU_ON_VALUE,
    ):
        self._num_gpu = _normalize(default_num_gpu)
        # "켜짐" 복원값: env 기본이 GPU 사용(≠0)이면 그 값을, 아니면 인자값을 쓴다.
        if self._num_gpu != 0:
            self._gpu_on_value = self._num_gpu
        else:
            self._gpu_on_value = _normalize(gpu_on_value) or DEFAULT_GPU_ON_VALUE
        self._consumers: list[Callable[[int], None]] = []

    # ── 소비자 연동 ───────────────────────────────────
    def register_consumer(self, setter: Callable[[int], None]) -> None:
        """num_gpu 변경을 반영할 서비스 세터를 등록하고 현재 값을 즉시 적용한다."""
        self._consumers.append(setter)
        try:
            setter(self._num_gpu)
        except Exception as e:
            logger.warning("[System] 소비자 초기 적용 실패: %s", e)

    def _notify(self) -> None:
        for setter in self._consumers:
            try:
                setter(self._num_gpu)
            except Exception as e:
                logger.warning("[System] 소비자 갱신 실패: %s", e)

    # ── 상태 조회 ─────────────────────────────────────
    @property
    def num_gpu(self) -> int:
        return self._num_gpu

    @property
    def gpu_enabled(self) -> bool:
        return self._num_gpu != 0

    @property
    def gpu_on_value(self) -> int:
        return self._gpu_on_value

    @staticmethod
    def describe(num_gpu: int) -> str:
        """num_gpu 값을 사람이 읽을 수 있는 문구로 변환한다."""
        if num_gpu == 0:
            return "CPU 전용"
        if num_gpu < 0:
            return "GPU 자동"
        return f"GPU {num_gpu} 레이어"

    # ── 제어 ──────────────────────────────────────────
    def set_gpu(self, enabled: bool) -> None:
        if enabled:
            if self._gpu_on_value == 0:
                self._gpu_on_value = DEFAULT_GPU_ON_VALUE
            self._num_gpu = self._gpu_on_value
        else:
            # 켜져 있던 값을 복원용으로 기억해 둔다.
            if self._num_gpu != 0:
                self._gpu_on_value = self._num_gpu
            self._num_gpu = 0
        self._notify()

    def set_gpu_layers(self, layers: int) -> None:
        layers = max(0, layers)
        if layers > 0:
            self._gpu_on_value = layers
        self._num_gpu = layers
        self._notify()
