import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_SENT_IDS = 1000
DEFAULT_WATCHLIST: Dict[str, str] = {
    "09988": "알리바바",
    "300750": "CATL",
}


class SentNewsTracker:
    def __init__(self, file_path: Path, max_size: int = MAX_SENT_IDS):
        self._file_path = file_path
        self._max_size = max_size
        self._ids: list[str] = []
        self._id_set: set[str] = set()
        self._pending: set[str] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if self._file_path.exists():
            self._ids = json.loads(self._file_path.read_text(encoding="utf-8"))
            self._id_set = set(self._ids)

    async def reserve(self, article_id: str) -> bool:
        async with self._lock:
            if article_id in self._id_set or article_id in self._pending:
                return False
            self._pending.add(article_id)
            return True

    async def confirm(self, article_id: str) -> None:
        async with self._lock:
            self._pending.discard(article_id)
            if article_id in self._id_set:
                return
            self._ids.append(article_id)
            self._id_set.add(article_id)
            if len(self._ids) > self._max_size:
                oldest = self._ids.pop(0)
                self._id_set.discard(oldest)

    async def release(self, article_id: str) -> None:
        async with self._lock:
            self._pending.discard(article_id)

    async def persist(self):
        async with self._lock:
            data = json.dumps(self._ids, ensure_ascii=False)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")


class WatchlistManager:
    def __init__(
        self,
        file_path: Path,
        default_watchlist: Dict[str, str] | None = None,
    ):
        self._file_path = file_path
        self._default_watchlist = default_watchlist or DEFAULT_WATCHLIST
        self._watchlist: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not self._file_path.exists():
            self._watchlist = self._default_watchlist.copy()
            self._file_path.write_text(
                json.dumps(self._watchlist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            self._watchlist = json.loads(self._file_path.read_text(encoding="utf-8"))

    async def _persist(self):
        data = json.dumps(self._watchlist, ensure_ascii=False, indent=2)
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


class MarketViewManager:
    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._data = {"view": None, "updated_at": None, "last_result": None}
            self._persist()
            return
        try:
            self._data = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[MarketView] failed to load state, resetting: %s", e)
            self._data = {"view": None, "updated_at": None, "last_result": None}
            self._persist()

    def _persist(self) -> None:
        self._file_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_view(self) -> str | None:
        view = self._data.get("view")
        return view if isinstance(view, str) and view.strip() else None

    def set_view(self, text: str) -> None:
        self._data["view"] = text.strip()
        self._data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._persist()

    def clear_view(self) -> None:
        self._data["view"] = None
        self._data["updated_at"] = None
        self._data["last_result"] = None
        self._persist()

    def get_last_result(self) -> dict[str, Any] | None:
        result = self._data.get("last_result")
        return result if isinstance(result, dict) else None

    def save_result(self, result: dict[str, Any]) -> None:
        self._data["last_result"] = result
        self._persist()
