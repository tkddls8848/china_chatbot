import asyncio
import json
from pathlib import Path


class SentNewsTracker:
    """중복 전송 방지. max_size가 0 이하이면 보낸 기사 ID를 계속 보관한다."""

    def __init__(self, file_path: Path, max_size: int = 0):
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
        """처리 중이거나 이미 보낸 ID가 아니면 pending으로 예약한다."""
        async with self._lock:
            if article_id in self._id_set or article_id in self._pending:
                return False
            self._pending.add(article_id)
            return True

    async def confirm(self, article_id: str) -> None:
        """텔레그램 전송 성공 후 sent 목록에 확정한다."""
        async with self._lock:
            self._pending.discard(article_id)
            if article_id in self._id_set:
                return
            self._ids.append(article_id)
            self._id_set.add(article_id)
            if self._max_size > 0 and len(self._ids) > self._max_size:
                oldest = self._ids.pop(0)
                self._id_set.discard(oldest)

    async def release(self, article_id: str) -> None:
        """번역 또는 전송 실패 시 다음 주기에 재시도할 수 있도록 예약을 해제한다."""
        async with self._lock:
            self._pending.discard(article_id)

    async def persist(self):
        async with self._lock:
            data = json.dumps(self._ids, ensure_ascii=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")
