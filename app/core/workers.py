"""뉴스 긴급 경로와 분리된 비긴급 작업 실행기."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

from core.config import NON_URGENT_WORKER_COUNT

_NON_URGENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=NON_URGENT_WORKER_COUNT,
    thread_name_prefix="non-urgent",
)


async def run_non_urgent(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """비긴급·블로킹 작업을 전용 워커에서 실행한다."""
    call = partial(func, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(_NON_URGENT_EXECUTOR, call)
