"""Polymarket 일별 스냅숏 저장과 24시간 변화 정렬.

하루 한 번(08:35 KST) 게이트를 통과한 계약의 Yes 확률을 통째로 적어 두고,
**전일과 당일 스냅숏에 모두 있는 같은 `conditionId`만** 짝지어 변화를 낸다.
이 제약이 이 모듈의 존재 이유다. 계약은 만기가 되면 사라지고 비슷한 질문이
새 slug로 다시 열리는데, 그 둘을 이어 붙이면 어제 90%였던 계약이 오늘 새로
열린 30% 계약과 비교되어 -60pp라는 가짜 급변이 만들어진다. 그래서:

- 만료 계약을 다른 slug로 **잇지 않는다.**
- 빠진 날을 앞 값으로 **채우지 않는다.** 전일 스냅숏이 없으면 그날 변화는 없다.
- 스냅숏 시각이 다른 날끼리 비교하지 않도록 **하루 한 번만** 기록한다
  (같은 날 두 번째 호출은 저장하지 않는다). 08:35 스냅숏과 19:00 스냅숏을
  섞으면 일중 변동이 일간 변화로 둔갑한다.

집계는 세 단계로 접는다.

1. 계약 → **이벤트 중앙값.** S&P 임계값 8개짜리 이벤트 하나가 한반도 이벤트
   하나보다 8배 세게 반영되는 일을 막는다.
2. 이벤트 → **theme 중앙값.**
3. theme → **단순 평균.** theme마다 같은 무게를 줘서 한 주제가 지표를 끌고
   가지 못하게 하고, 그 기여도를 함께 남겨 승격 게이트가 검증할 수 있게 한다.

값의 부호는 계약의 polarity를 곱한 뒤의 **위험선호 방향**이다(+ = risk-on).
국가별 뉴스 감성 점수와는 축이 다르므로 절대 합산하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from core.clock import now, today

logger = logging.getLogger(__name__)

# 승격 게이트(docs/aws-next-steps.md). 백필이 이 기준으로 판정한다.
PROMOTION_WINDOW_DAYS = 30
# 라이브 수집에서 확인하는 것은 **가동률뿐이다.** 게이트의 실질은 백필이 이미
# 판정했고 일주일 더 본다고 달라지지 않는다. 반대로 "매일 08:35에 봇이 살아
# 있는가"는 백필이 절대 답하지 못한다 — 과거 시세에는 우리 job의 흔적이 없다.
UPTIME_WINDOW_DAYS = 7
_MIN_UPTIME_DAYS = 6
_MIN_SNAPSHOT_DAYS = 24
_MIN_DELTA_DAYS = 24
_MIN_EVENTS_PER_DAY = 3
_MIN_DENSE_DAY_RATIO = 0.8
_MIN_THEMES = 3
_MAX_THEME_CONTRIBUTION = 0.5
_MAX_MEDIAN_SPREAD = 0.05


def _median(values: list[float]) -> float:
    return float(median(values))


def align_daily_change(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """전일·당일 스냅숏에서 24시간 위험선호 변화(pp)를 만든다.

    공통 계약이 하나도 없으면 None이다. polarity가 두 날 사이에 달라진 계약은
    규칙이 바뀐 흔적이므로 제외한다 — 부호가 뒤집힌 채로 이어 붙이면 변화가
    아니라 규칙 개정을 그리게 된다.
    """
    by_event: dict[str, list[float]] = {}
    event_theme: dict[str, str] = {}
    contracts = 0

    for condition_id, entry in sorted(current.items()):
        earlier = previous.get(condition_id)
        if earlier is None:
            continue
        polarity = entry.get("polarity")
        if polarity != earlier.get("polarity") or polarity not in (1, -1):
            continue
        before, after = earlier.get("price"), entry.get("price")
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        theme = str(entry.get("theme") or "")
        if not theme:
            continue
        # 이벤트 식별자가 없는 계약은 그 자체를 이벤트로 본다.
        event = str(entry.get("event_id") or "") or condition_id
        by_event.setdefault(event, []).append(
            (float(after) - float(before)) * 100.0 * polarity
        )
        # 한 이벤트에 서로 다른 theme의 자식이 섞여 있으면 첫 계약의 theme으로
        # 계상한다. 값 자체는 이미 위험선호 축으로 정렬돼 있어 섞여도 무방하고,
        # theme은 기여도 회계용 이름표일 뿐이다.
        event_theme.setdefault(event, theme)
        contracts += 1

    if not by_event:
        return None

    by_theme: dict[str, list[float]] = {}
    for event, changes in by_event.items():
        by_theme.setdefault(event_theme[event], []).append(_median(changes))

    theme_changes = {theme: _median(values) for theme, values in by_theme.items()}
    return {
        "change_pp": sum(theme_changes.values()) / len(theme_changes),
        "themes": theme_changes,
        "event_count": len(by_event),
        "contract_count": contracts,
    }


class PolymarketConsensusStore:
    """일별 스냅숏 캐시. `data/market_sentiment/polymarket_consensus.json`."""

    def __init__(self, file_path: Path, retention_days: int = 31):
        self._file_path = file_path
        # 30일치 변화를 내려면 31일치 스냅숏이 필요하다(첫날은 비교 대상이 없다).
        self._retention_days = max(2, retention_days)
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _cutoff(self) -> date:
        return today() - timedelta(days=self._retention_days - 1)

    def _evict(self) -> None:
        cutoff = self._cutoff()
        kept = {}
        for key, snapshot in self._snapshots.items():
            try:
                if date.fromisoformat(key) >= cutoff:
                    kept[key] = snapshot
            except (TypeError, ValueError):
                continue
        self._snapshots = kept

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("[POLYMARKET] 스냅숏을 읽지 못해 빈 상태로 시작합니다.")
            return
        if not isinstance(raw, dict):
            return
        self._snapshots = {
            key: snapshot
            for key, snapshot in raw.items()
            if isinstance(snapshot, dict) and isinstance(snapshot.get("contracts"), dict)
        }
        before = len(self._snapshots)
        self._evict()
        if len(self._snapshots) != before:
            self._write()

    def _write(self) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(self._snapshots, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("[POLYMARKET] 스냅숏을 저장하지 못했습니다: %s", exc)

    async def put_snapshot(self, day: date, contracts: dict[str, dict[str, Any]]) -> bool:
        """하루치 스냅숏을 기록한다. 그날이 이미 있으면 저장하지 않고 False.

        덮어쓰지 않는 이유는 비교 가능성 때문이다. 스냅숏은 매일 같은 시각의
        가격이어야 하고, 재실행으로 오후 가격이 들어오면 그날 변화가 08:35 대
        오후가 되어 다른 날들과 같은 축에 놓을 수 없다.
        """
        if not contracts:
            return False
        key = day.isoformat()
        async with self._lock:
            if key in self._snapshots:
                return False
            self._snapshots[key] = {
                "date": key,
                "captured_at": now().isoformat(timespec="seconds"),
                "contracts": contracts,
            }
            self._evict()
            self._write()
            return True

    async def snapshot_dates(self) -> list[date]:
        async with self._lock:
            return sorted(date.fromisoformat(key) for key in self._snapshots)

    async def daily_changes(self, lookback_days: int) -> list[dict[str, Any]]:
        """최근 기간의 일별 변화를 오래된 순으로 돌려준다.

        하루(D)의 값은 D와 **D-1** 스냅숏이 모두 있을 때만 만든다. 중간이 비면
        그 자리는 그냥 없는 채로 둔다 — 이어 그리면 이틀치 변화가 하루치로
        보인다.
        """
        current_day = today()
        window = [
            current_day - timedelta(days=offset)
            for offset in range(max(1, lookback_days))
        ]
        changes: list[dict[str, Any]] = []
        async with self._lock:
            for day in sorted(window):
                snapshot = self._snapshots.get(day.isoformat())
                earlier = self._snapshots.get((day - timedelta(days=1)).isoformat())
                if snapshot is None or earlier is None:
                    continue
                change = align_daily_change(
                    earlier.get("contracts") or {},
                    snapshot.get("contracts") or {},
                )
                if change is None:
                    continue
                changes.append({"date": day.isoformat(), **change})
        return changes

    async def uptime(self, window_days: int = UPTIME_WINDOW_DAYS) -> dict[str, Any]:
        """최근 기간에 스냅숏이 남은 날 수. 승격의 나머지 절반이다.

        백필과 나란히 돌리는 라이브 수집이 답하는 유일한 질문이라, 게이트 표와
        같은 모양(value·threshold·passed)으로 돌려준다.
        """
        oldest = today() - timedelta(days=max(1, window_days) - 1)
        days = [day for day in await self.snapshot_dates() if day >= oldest]
        return {
            "window_days": window_days,
            "value": len(days),
            "threshold": _MIN_UPTIME_DAYS,
            "passed": len(days) >= _MIN_UPTIME_DAYS,
            "last_date": days[-1].isoformat() if days else "",
        }

    async def _spreads(self, window_days: int) -> list[float]:
        current_day = today()
        oldest = current_day - timedelta(days=max(1, window_days) - 1)
        values: list[float] = []
        async with self._lock:
            for key, snapshot in self._snapshots.items():
                try:
                    if date.fromisoformat(key) < oldest:
                        continue
                except ValueError:
                    continue
                for entry in (snapshot.get("contracts") or {}).values():
                    spread = entry.get("spread")
                    if isinstance(spread, (int, float)):
                        values.append(float(spread))
        return values

    async def promotion_report(
        self,
        window_days: int = PROMOTION_WINDOW_DAYS,
    ) -> dict[str, Any]:
        """승격 게이트를 계산한다(docs/aws-next-steps.md 3-3).

        하나라도 실패하면 패널을 켜지 않는다. 사람이 JSON을 열어 세는 대신
        `/system polymarket`이 이 값을 그대로 보여 준다.
        """
        current_day = today()
        oldest = current_day - timedelta(days=max(1, window_days) - 1)
        snapshot_days = [day for day in await self.snapshot_dates() if day >= oldest]
        changes = await self.daily_changes(window_days)

        dense_days = sum(
            1 for change in changes if change["event_count"] >= _MIN_EVENTS_PER_DAY
        )
        dense_ratio = dense_days / len(changes) if changes else 0.0

        contribution_totals: dict[str, float] = {}
        for change in changes:
            for theme, value in change["themes"].items():
                contribution_totals[theme] = contribution_totals.get(theme, 0.0) + abs(
                    value
                )
        magnitude = sum(contribution_totals.values())
        top_contribution = (
            max(contribution_totals.values()) / magnitude if magnitude else 0.0
        )
        spreads = await self._spreads(window_days)
        median_spread = _median(spreads) if spreads else 1.0

        criteria = {
            "snapshot_days": {
                "value": len(snapshot_days),
                "threshold": _MIN_SNAPSHOT_DAYS,
                "passed": len(snapshot_days) >= _MIN_SNAPSHOT_DAYS,
            },
            "delta_days": {
                "value": len(changes),
                "threshold": _MIN_DELTA_DAYS,
                "passed": len(changes) >= _MIN_DELTA_DAYS,
            },
            "dense_day_ratio": {
                "value": round(dense_ratio, 3),
                "threshold": _MIN_DENSE_DAY_RATIO,
                "passed": dense_ratio >= _MIN_DENSE_DAY_RATIO,
            },
            "theme_count": {
                "value": len(contribution_totals),
                "threshold": _MIN_THEMES,
                "passed": len(contribution_totals) >= _MIN_THEMES,
            },
            "top_theme_contribution": {
                "value": round(top_contribution, 3),
                "threshold": _MAX_THEME_CONTRIBUTION,
                "passed": bool(magnitude) and top_contribution <= _MAX_THEME_CONTRIBUTION,
            },
            "median_spread": {
                "value": round(median_spread, 4),
                "threshold": _MAX_MEDIAN_SPREAD,
                "passed": bool(spreads) and median_spread <= _MAX_MEDIAN_SPREAD,
            },
        }
        return {
            "window_days": window_days,
            "criteria": criteria,
            "passed": all(item["passed"] for item in criteria.values()),
        }
