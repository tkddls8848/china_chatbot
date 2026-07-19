import asyncio
import json
from pathlib import Path
from typing import Dict, Optional

DEFAULT_WATCHLIST: Dict[str, str] = {}


class WatchlistManager:
    """관심종목 관리"""

    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._watchlist: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not self._file_path.exists():
            self._watchlist = DEFAULT_WATCHLIST.copy()
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(self._watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            self._watchlist = json.loads(self._file_path.read_text(encoding="utf-8"))

    async def _persist(self):
        data = json.dumps(self._watchlist, ensure_ascii=False, indent=2)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")

    async def get_all(self) -> Dict[str, str]:
        async with self._lock:
            return self._watchlist.copy()

    async def add(self, code: str, name: str) -> None:
        async with self._lock:
            self._watchlist[code] = name
            await self._persist()

    async def remove(self, code: str) -> Optional[str]:
        async with self._lock:
            name = self._watchlist.pop(code, None)
            if name is not None:
                await self._persist()
            return name
