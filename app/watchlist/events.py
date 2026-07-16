"""관심리스트 편입·편출 이벤트 로그.

이벤트 시점 가격을 함께 기록해 주간 성적표(시장뷰 큐레이션 피드백 루프)의
근거가 된다. 가격 조회는 최선 노력이며 실패하면 None으로 남긴다.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WatchlistEventLog:
    def __init__(self, file_path: Path, max_events: int = 500):
        self._file_path = file_path
        self._max_events = max_events
        self._events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(raw, list):
            self._events = [e for e in raw if isinstance(e, dict)]

    async def record(
        self,
        event: str,
        code: str,
        name: str,
        price: float | None,
        reason: str = "",
    ) -> None:
        async with self._lock:
            self._events.append(
                {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "event": event,
                    "code": code,
                    "name": name,
                    "price": price,
                    "reason": reason[:200],
                }
            )
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
            data = json.dumps(self._events, ensure_ascii=False, indent=2)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._file_path.write_text, data, encoding="utf-8")

    async def snapshot(self, lookback_days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.now() - timedelta(days=max(1, lookback_days))
        async with self._lock:
            result = []
            for event in self._events:
                try:
                    if datetime.fromisoformat(str(event.get("ts"))) >= cutoff:
                        result.append(dict(event))
                except (TypeError, ValueError):
                    continue
            return result


async def record_watchlist_event(
    bot_data: dict,
    event: str,
    code: str,
    name: str,
    reason: str = "",
) -> None:
    """핸들러 공용 헬퍼. 이벤트 로그가 없으면 조용히 무시한다."""
    event_log: WatchlistEventLog | None = bot_data.get("watchlist_events")
    if event_log is None:
        return
    price = None
    quote_service = bot_data.get("quote_service")
    if quote_service is not None and getattr(quote_service, "enabled", False):
        try:
            price = await asyncio.to_thread(quote_service.get_price, code)
        except Exception as e:
            logger.debug("[EVENTS] %s 가격 조회 실패: %s", code, e)
    try:
        await event_log.record(event, code, name, price, reason)
    except Exception as e:
        logger.warning("[EVENTS] 이벤트 기록 실패(%s %s): %s", event, code, e)


def build_scorecard_lines(
    events: list[dict[str, Any]],
    watchlist: dict[str, str],
    current_prices: dict[str, float | None],
) -> dict[str, list[str]]:
    """이벤트와 현재가로 성적표 라인을 만든다(순수 함수, 테스트 대상).

    - 편입 후 아직 보유 중: 편입가 대비 현재가 수익률
    - 편출: 편출가 대비 현재가 변화(음수면 편출이 옳았던 셈)
    """
    added_lines: list[str] = []
    removed_lines: list[str] = []

    def pct(from_price: Any, to_price: Any) -> float | None:
        try:
            from_value = float(from_price)
            to_value = float(to_price)
        except (TypeError, ValueError):
            return None
        if from_value == 0:
            return None
        return (to_value - from_value) / from_value * 100

    # 같은 코드의 최신 이벤트만 평가한다(추가→삭제→추가 반복 대응).
    latest_by_code: dict[str, dict[str, Any]] = {}
    for event in events:
        code = str(event.get("code") or "")
        if code:
            latest_by_code[code] = event

    for code, event in latest_by_code.items():
        name = str(event.get("name") or watchlist.get(code) or code)
        kind = event.get("event")
        entry_price = event.get("price")
        current = current_prices.get(code)
        ts = str(event.get("ts") or "")[:10]
        change = pct(entry_price, current)
        change_part = f"{change:+.1f}%" if change is not None else "가격 데이터 없음"

        if kind == "add" and code in watchlist:
            added_lines.append(f"• {name} ({code}) {ts} 편입 → {change_part}")
        elif kind == "remove":
            removed_lines.append(f"• {name} ({code}) {ts} 편출 → 이후 {change_part}")

    return {"added": added_lines, "removed": removed_lines}
