"""뉴스 긴급 경로와 분리된 비긴급 작업 실행기."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import count
from threading import Lock
from typing import Any, Callable

from core.config import NON_URGENT_WORKER_COUNT

_NON_URGENT_EXECUTORS = tuple(
    ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=f"non-urgent-{index + 1}",
    )
    for index in range(NON_URGENT_WORKER_COUNT)
)
_NON_URGENT_EXECUTOR_SEQUENCE = count()
_NON_URGENT_EXECUTOR_LOCK = Lock()


def _next_non_urgent_executor() -> ThreadPoolExecutor:
    """1→N 순서로 각 단일 스레드 실행기에 작업을 배정한다."""
    with _NON_URGENT_EXECUTOR_LOCK:
        index = next(_NON_URGENT_EXECUTOR_SEQUENCE) % len(_NON_URGENT_EXECUTORS)
    return _NON_URGENT_EXECUTORS[index]


async def run_non_urgent(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """비긴급·블로킹 작업을 라운드 로빈 전용 워커에서 실행한다."""
    call = partial(func, *args, **kwargs)
    executor = _next_non_urgent_executor()
    return await asyncio.get_running_loop().run_in_executor(executor, call)
