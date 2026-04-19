from datetime import datetime, timezone
from typing import Any


class TtlCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, dict] = {}

    def get(self, key: str) -> tuple[bool, Any]:
        entry = self._store.get(key)
        if not entry:
            return False, None
        age = (datetime.now(timezone.utc) - entry["ts"]).total_seconds()
        if age >= self._ttl:
            return False, None
        return True, entry["data"]

    def set(self, key: str, data: Any) -> None:
        self._store[key] = {"ts": datetime.now(timezone.utc), "data": data}

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def info(self) -> dict[str, dict]:
        now = datetime.now(timezone.utc)
        return {
            k: {
                "age_seconds": round((now - v["ts"]).total_seconds()),
                "fresh": (now - v["ts"]).total_seconds() < self._ttl,
            }
            for k, v in self._store.items()
        }
