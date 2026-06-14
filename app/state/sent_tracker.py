import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path


class SentNewsTracker:
    """중복 전송 방지. retention_days 이전에 저장된 ID는 자동 만료된다."""

    def __init__(self, file_path: Path, max_size: int = 0, retention_days: int = 7):
        self._file_path = file_path
        self._retention_days = retention_days
        self._id_ts: dict[str, str] = {}  # id → ISO timestamp
        self._pending: set[str] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _cutoff(self) -> datetime:
        return datetime.now() - timedelta(days=self._retention_days)

    def _evict(self) -> None:
        cutoff = self._cutoff()
        expired = [
            k for k, ts in self._id_ts.items()
            if datetime.fromisoformat(ts) < cutoff
        ]
        for k in expired:
            del self._id_ts[k]

    def _load(self):
        if not self._file_path.exists():
            return
        raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            # 구형 포맷(list) → 현재 시각으로 마이그레이션
            now = datetime.now().isoformat()
            self._id_ts = {item: now for item in raw if isinstance(item, str)}
        elif isinstance(raw, dict):
            self._id_ts = raw
        self._evict()

    async def reserve(self, article_id: str) -> bool:
        """처리 중이거나 이미 보낸 ID가 아니면 pending으로 예약한다."""
        async with self._lock:
            if article_id in self._id_ts or article_id in self._pending:
                return False
            self._pending.add(article_id)
            return True

    async def confirm(self, article_id: str) -> None:
        """텔레그램 전송 성공 후 sent 목록에 확정한다."""
        async with self._lock:
            self._pending.discard(article_id)
            if article_id in self._id_ts:
                return
            self._id_ts[article_id] = datetime.now().isoformat()

    async def release(self, article_id: str) -> None:
        """번역 또는 전송 실패 시 다음 주기에 재시도할 수 있도록 예약을 해제한다."""
        async with self._lock:
            self._pending.discard(article_id)

    async def persist(self):
        async with self._lock:
            self._evict()
            data = json.dumps(self._id_ts, ensure_ascii=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")
