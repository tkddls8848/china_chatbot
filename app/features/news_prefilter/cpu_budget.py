"""사전선별 백그라운드 유지보수용 일일 CPU 예산 상태."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core.clock import now
from core.storage import write_json_atomic


class DailyCpuBudget:
    def __init__(
        self,
        state_file: Path,
        daily_budget_seconds: float,
        reserve_ratio: float,
    ):
        self._state_file = state_file
        self._daily_budget_seconds = max(0.0, daily_budget_seconds)
        self._reserve_ratio = min(1.0, max(0.0, reserve_ratio))
        self._state = self._load_state()
        self._last_process_cpu = time.process_time()
        self._background_since_checkpoint = 0.0

    @staticmethod
    def _utc_day() -> str:
        # Neurons 예산과 같은 UTC 00시 리셋 — core/clock.py의 now()/today()(KST)를
        # 쓰지 않는 명시적 예외. 두 예산의 경계를 맞춰야 한쪽이 소진된 날을
        # 다른 쪽 로그와 같은 일자로 읽을 수 있다.
        return datetime.now(timezone.utc).date().isoformat()

    def _load_state(self) -> dict[str, float | str]:
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            raw = {}
        day = self._utc_day()
        if not isinstance(raw, dict) or raw.get("utc_day") != day:
            return {
                "utc_day": day,
                "foreground_cpu_seconds": 0.0,
                "background_cpu_seconds": 0.0,
            }
        return {
            "utc_day": day,
            "foreground_cpu_seconds": float(raw.get("foreground_cpu_seconds") or 0.0),
            "background_cpu_seconds": float(raw.get("background_cpu_seconds") or 0.0),
        }

    def _reset_day_if_needed(self) -> None:
        day = self._utc_day()
        if self._state["utc_day"] == day:
            return
        self._state = {
            "utc_day": day,
            "foreground_cpu_seconds": 0.0,
            "background_cpu_seconds": 0.0,
        }
        self._last_process_cpu = time.process_time()
        self._background_since_checkpoint = 0.0

    def _persist(self) -> None:
        payload = dict(self._state)
        payload["budget_seconds"] = self._daily_budget_seconds
        payload["reserve_ratio"] = self._reserve_ratio
        payload["updated_at"] = now().isoformat(timespec="seconds")
        write_json_atomic(self._state_file, payload)

    def account_foreground_cpu(self) -> None:
        self._reset_day_if_needed()
        current = time.process_time()
        delta = max(0.0, current - self._last_process_cpu)
        foreground = max(0.0, delta - self._background_since_checkpoint)
        self._state["foreground_cpu_seconds"] += foreground
        self._last_process_cpu = current
        self._background_since_checkpoint = 0.0
        self._persist()

    def record_background_cpu(self, cpu_seconds: float) -> None:
        self._reset_day_if_needed()
        used = max(0.0, float(cpu_seconds))
        self._state["background_cpu_seconds"] += used
        self._background_since_checkpoint += used
        self._persist()

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._daily_budget_seconds - self._used_seconds())

    def status(self) -> dict[str, float | str]:
        used = self._used_seconds()
        return {
            "utc_day": self._state["utc_day"],
            "budget_seconds": self._daily_budget_seconds,
            "used_seconds": used,
            "remaining_seconds": max(0.0, self._daily_budget_seconds - used),
            "reserve_ratio": self._reserve_ratio,
        }

    def _used_seconds(self) -> float:
        return float(self._state["foreground_cpu_seconds"]) + float(
            self._state["background_cpu_seconds"]
        )
