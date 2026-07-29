import asyncio
import json
from collections.abc import Callable
from pathlib import Path


class WatchlistManager:
    """관심종목 관리"""

    def __init__(
        self,
        file_path: Path,
        code_resolver: Callable[[str], str | None] | None = None,
    ):
        self._file_path = file_path
        self._code_resolver = code_resolver
        self._watchlist: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not self._file_path.exists():
            self._watchlist = {}
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(self._watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            self._watchlist = json.loads(self._file_path.read_text(encoding="utf-8"))
            self._normalize_loaded_codes()

    def _normalize_loaded_codes(self) -> None:
        if self._code_resolver is None:
            return
        normalized: dict[str, str] = {}
        changed = False
        for code, name in self._watchlist.items():
            canonical = self._canonical_code(code)
            if canonical in normalized:
                if code == canonical:
                    normalized[canonical] = name
                changed = True
                continue
            normalized[canonical] = name
            changed = changed or canonical != code
        if not changed:
            return
        self._watchlist = normalized
        self._file_path.write_text(
            json.dumps(self._watchlist, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _canonical_code(self, code: str) -> str:
        if self._code_resolver is None:
            return code
        return self._code_resolver(code) or code

    async def _persist(self):
        data = json.dumps(self._watchlist, ensure_ascii=False, indent=2)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")

    async def get_all(self) -> dict[str, str]:
        async with self._lock:
            return self._watchlist.copy()

    async def add(self, code: str, name: str) -> None:
        async with self._lock:
            self._watchlist[self._canonical_code(code)] = name
            await self._persist()

    async def remove(self, code: str) -> str | None:
        async with self._lock:
            name = self._watchlist.pop(self._canonical_code(code), None)
            if name is not None:
                await self._persist()
            return name
