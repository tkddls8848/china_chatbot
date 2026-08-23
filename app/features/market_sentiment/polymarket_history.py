"""CLOB 과거 시세로 지난 30일 스냅숏을 소급 재구성한다(백필).

30일 섀도 파일럿을 하루로 줄이려고 만들었다. 08:35 스냅숏은 그날의 확률을
적어 두는 일뿐인데, 같은 값이 CLOB `prices-history`에 이미 남아 있다. 그래서
**지난 31일치 확률을 지금 한 번에 읽어 스냅숏 파일을 소급 작성**하고, 라이브
파일럿과 똑같은 `PolymarketConsensusStore.promotion_report()`로 판정한다.

읽는 곳이 Gamma가 아니라 CLOB(`https://clob.polymarket.com`)이고 키도 다르다 —
`conditionId`가 아니라 Yes 다리의 `clobTokenIds`다. 인증은 여전히 없고 LLM도
거치지 않으므로 **추가 Neurons는 0**이다.

**백필로는 판정할 수 없는 것이 있다. 이 한계를 지운 채로 승격하지 않는다.**

1. **유동성·호가는 조회 시점 값 하나뿐이다.** Gamma는 과거 시점의 `liquidityNum`·
   `spread`를 주지 않는다. 그래서 수량 게이트는 31일 내내 "오늘의 유동성"으로
   적용된다 — 20일 전에는 얕았다가 지금 두꺼워진 계약이 그때도 통과한 것처럼
   섞인다. 라이브 수집에는 없는 낙관 편향이다.
2. **median spread 게이트는 오늘 선정분으로만 계산된다.** 과거 호가가 없으므로
   과거 스냅숏에는 `spread`를 아예 적지 않는다(0.0으로 채우면 없는 근거가
   통과로 둔갑한다). 저장·집계 형식은 그대로다 — `_spreads()`가 숫자가 아닌
   값을 건너뛴다.
3. **수집 job의 가동률은 재현되지 않는다.** 백필은 매일 08:35에 봇이 살아
   있었는지를 묻지 않는다. "성공 스냅숏 30일 중 24일"은 데이터가 그만큼
   있었는지를 말할 뿐, 우리 cron이 그만큼 돌 것인지는 라이브로만 확인된다.
4. **삭제·비상장된 마켓은 복원할 수 없다.** Gamma 목록에서 사라진 계약은
   조회 대상에 아예 들어오지 않는다.

만기가 온 계약을 함께 읽는 이유가 (4)와 이어진다. 지금 열려 있는 계약만으로
과거를 그리면 **살아남은 계약만 남아** 짝이 끊기는 날이 하나도 없는 그림이
나온다. 그래서 창 안에서 만기가 온 계약도 후보에 넣고, 만기 이틀 전까지의
가격만 쓴다(`moment_rejection`이 날짜마다 다시 판단한다).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from core.clock import JST, ensure_jst, now, today
from features.market_sentiment.polymarket import (
    PolymarketClient,
    PolymarketContract,
    PolymarketError,
    _JsonEndpoint,
)
from features.market_sentiment.polymarket_rules import (
    classify_theme,
    moment_rejection,
    static_rejection,
)
from features.market_sentiment.snapshot import SNAPSHOT_HOUR, SNAPSHOT_MINUTE

logger = logging.getLogger(__name__)

# 백필이 판정하지 못하는 게이트와 그 사유. 백필 보고서를 그리는 곳이 둘
# (`app/polymarket_backfill.py`와 `/system polymarket`)이라 여기서 한 번만
# 적는다 — 두 벌로 두면 한쪽에서 조용히 사라진다.
BACKFILL_CAVEATS = {
    "median_spread": "과거 호가가 없어 오늘 선정분으로만 계산됨",
    "snapshot_days": "데이터 유무일 뿐, job 가동률은 라이브에서 확인",
}

# 시세 이력의 해상도(분). 08:35 직전 값을 집으므로 시간 단위면 충분하고,
# 31일 × 24점이면 계약당 응답도 가볍다.
_FIDELITY_MINUTES = 60
# 목표 시각보다 이만큼 더 오래된 값은 그날 가격으로 인정하지 않는다. 거래가
# 끊긴 구간을 앞 값으로 끌어오면 없는 날이 있는 날로 둔갑한다.
_MAX_SAMPLE_LAG = timedelta(hours=6)
# CLOB이 `fidelity=60`(분)에 31일 폭을 한 번에 주면 `400 interval is too
# long`으로 거절한다(실측 2026-08-22, 문서화되지 않은 서버 쪽 상한). 정확한
# 경계를 찾는 대신 폴리마켓 자기 API의 `interval` enum에 `1w`가 1급 값으로
# 있는 걸 근거로 일주일 폭은 항상 통과한다고 보고 그 폭으로 나눠 이어 붙인다.
_MAX_HISTORY_CHUNK_DAYS = 7


class PolymarketHistoryClient(_JsonEndpoint):
    """CLOB `/prices-history` 읽기 전용 클라이언트."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__(
            url=f"{base_url.rstrip('/')}/prices-history",
            timeout=timeout,
            session=session,
            sleep=sleep,
        )

    def fetch_price_history(
        self,
        token_id: str,
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, float]]:
        """`start`~`end`를 `_MAX_HISTORY_CHUNK_DAYS` 폭으로 나눠 이어 붙인다.

        CLOB이 한 번에 받는 폭에 상한을 두므로(위 상수 설명) 여러 번 나눠
        부른다. 한 조각이 실패하면(`PolymarketError`) 그대로 위로 던진다 —
        일부만 받은 이력을 "이 계약의 이력"으로 쓰면 빠진 구간이 없는 날로
        둔갑한다.
        """
        points: list[tuple[datetime, float]] = []
        step = timedelta(days=_MAX_HISTORY_CHUNK_DAYS)
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + step, end)
            payload = self._request(
                {
                    "market": token_id,
                    "startTs": int(chunk_start.timestamp()),
                    "endTs": int(chunk_end.timestamp()),
                    "fidelity": _FIDELITY_MINUTES,
                }
            )
            points.extend(parse_price_history(payload))
            chunk_start = chunk_end
        points.sort(key=lambda point: point[0])
        return points


def parse_price_history(payload: Any) -> list[tuple[datetime, float]]:
    """`{"history": [{"t": <unix초>, "p": <확률>}]}`를 시각 오름차순으로 읽는다.

    응답 봉투가 다르면 조용히 빈 목록을 주지 않고 `PolymarketError`로 세운다.
    빈 이력과 못 읽은 이력은 다른 사건인데, 섞이면 백필이 "그날은 거래가 없었다"는
    얼굴로 통째로 비어 버린다.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
        raise PolymarketError(
            "invalid_history",
            detail=f"expected a history list, got {str(payload)[:120]}",
        )

    points: list[tuple[datetime, float]] = []
    for item in payload["history"]:
        if not isinstance(item, dict):
            continue
        stamp, price = item.get("t"), item.get("p")
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            continue
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            continue
        if not 0.0 <= float(price) <= 1.0:
            continue
        points.append(
            (datetime.fromtimestamp(float(stamp), tz=JST), float(price))
        )
    points.sort(key=lambda point: point[0])
    return points


def snapshot_moment(day: date) -> datetime:
    """그날의 스냅숏 시각(08:35 JST). 라이브 job과 같은 축에 놓기 위한 기준이다."""
    return datetime(
        day.year, day.month, day.day, SNAPSHOT_HOUR, SNAPSHOT_MINUTE, tzinfo=JST
    )


def sample_price(
    history: list[tuple[datetime, float]],
    moment: datetime,
) -> float | None:
    """`moment` 이전의 마지막 값. 너무 오래됐거나 없으면 None."""
    latest: tuple[datetime, float] | None = None
    for stamp, price in history:
        if ensure_jst(stamp) > moment:
            break
        latest = (stamp, price)
    if latest is None:
        return None
    if moment - ensure_jst(latest[0]) > _MAX_SAMPLE_LAG:
        return None
    return latest[1]


@dataclass
class BackfillCandidate:
    """수량 게이트와 theme 분류를 통과한 후보 1건과 그 가격 이력."""

    contract: PolymarketContract
    theme: str
    polarity: int
    expired: bool
    history: list[tuple[datetime, float]] = field(default_factory=list)


@dataclass
class BackfillResult:
    snapshots: dict[date, dict[str, dict[str, Any]]]
    candidates: int
    expired_candidates: int
    history_failures: dict[str, int]
    rejected: dict[str, int]


def collect_candidates(
    client: PolymarketClient,
    *,
    min_volume: float,
    min_liquidity: float,
    max_spread: float,
    max_horizon_days: int,
    window_days: int,
) -> tuple[list[BackfillCandidate], dict[str, int]]:
    """열린 계약과 창 안에서 만기가 온 계약을 후보로 모은다.

    만기 계약에는 유동성·호가 게이트를 적용하지 않는다. 결제 뒤 값이라 당시
    유동성이 아니고, 그 값으로 거르면 "만기로 사라진 계약"이라는 관측 자체가
    통째로 빠져 짝이 끊기는 날이 없는 그림이 된다.
    """
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    candidates: dict[str, BackfillCandidate] = {}
    groups = (
        (
            False,
            client.fetch_open_contracts(
                min_volume=min_volume,
                min_liquidity=min_liquidity,
                max_horizon_days=max_horizon_days,
            ),
        ),
        (
            True,
            client.fetch_expired_contracts(
                min_volume=min_volume,
                since_days=window_days,
            ),
        ),
    )

    for expired, contracts in groups:
        for contract in contracts:
            if contract.condition_id in candidates:
                continue
            if expired:
                # 결제 뒤 유동성·호가는 당시 값이 아니다. 만기 뒤에도 남는
                # 누적 거래량만 본다.
                reason = "volume" if contract.volume < min_volume else ""
            else:
                reason = static_rejection(
                    contract,
                    min_volume=min_volume,
                    min_liquidity=min_liquidity,
                    max_spread=max_spread,
                )
            if reason:
                reject(reason)
                continue
            classified = classify_theme(contract.question)
            if classified is None:
                reject("no_theme")
                continue
            if not contract.yes_token_id:
                # 토큰 id가 없으면 과거 시세를 부를 키가 없다. 라이브 수집에는
                # 없는 탈락 사유라 따로 센다.
                reject("no_token_id")
                continue
            theme, polarity = classified
            candidates[contract.condition_id] = BackfillCandidate(
                contract=contract,
                theme=theme,
                polarity=polarity,
                expired=expired,
            )

    return list(candidates.values()), rejected


def load_histories(
    history_client: PolymarketHistoryClient,
    candidates: list[BackfillCandidate],
    *,
    window_days: int,
) -> dict[str, int]:
    """후보마다 창 전체의 가격 이력을 채운다. 실패는 사유별로 세어 돌려준다.

    한 계약이 실패해도 나머지는 계속 읽는다 — 백필은 일회성 도구라 중간에
    죽으면 처음부터 다시 받아야 하고, 그 사이 요청은 전부 버려진다.
    """
    start = snapshot_moment(today() - timedelta(days=window_days)) - _MAX_SAMPLE_LAG
    end = now()
    failures: dict[str, int] = {}
    for candidate in candidates:
        try:
            candidate.history = history_client.fetch_price_history(
                candidate.contract.yes_token_id,
                start=start,
                end=end,
            )
        except PolymarketError as error:
            failures[error.reason] = failures.get(error.reason, 0) + 1
            logger.warning(
                "[POLYMARKET] 이력 조회 실패 condition=%s reason=%s",
                candidate.contract.condition_id,
                error.reason,
            )
    return failures


def build_snapshots(
    candidates: list[BackfillCandidate],
    *,
    window_days: int,
    max_horizon_days: int,
) -> dict[date, dict[str, dict[str, Any]]]:
    """날짜별 스냅숏을 만든다. 형식은 라이브 job이 쓰는 것과 같다.

    `spread`는 **오늘 스냅숏에만** 넣는다. 과거 호가는 존재하지 않으므로 빈
    자리로 두고, 승격 게이트의 median spread는 오늘 선정분으로만 계산되게 한다.
    """
    current_day = today()
    snapshots: dict[date, dict[str, dict[str, Any]]] = {}

    for offset in range(window_days, -1, -1):
        day = current_day - timedelta(days=offset)
        moment = snapshot_moment(day)
        if moment > now():
            continue
        contracts: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            price = sample_price(candidate.history, moment)
            if price is None:
                continue
            if moment_rejection(
                candidate.contract,
                price,
                moment,
                max_horizon_days=max_horizon_days,
            ):
                continue
            entry: dict[str, Any] = {
                "price": price,
                "theme": candidate.theme,
                "polarity": candidate.polarity,
                "event_id": candidate.contract.event_id,
                "question": candidate.contract.question,
            }
            if day == current_day and not candidate.expired:
                entry["spread"] = candidate.contract.spread
            contracts[candidate.contract.condition_id] = entry
        if contracts:
            snapshots[day] = contracts
    return snapshots


def run_backfill(
    client: PolymarketClient,
    history_client: PolymarketHistoryClient,
    *,
    min_volume: float,
    min_liquidity: float,
    max_spread: float,
    max_horizon_days: int,
    window_days: int,
) -> BackfillResult:
    """후보 수집 → 이력 조회 → 날짜별 스냅숏 조립을 한 번에 돈다."""
    candidates, rejected = collect_candidates(
        client,
        min_volume=min_volume,
        min_liquidity=min_liquidity,
        max_spread=max_spread,
        max_horizon_days=max_horizon_days,
        window_days=window_days,
    )
    failures = load_histories(history_client, candidates, window_days=window_days)
    snapshots = build_snapshots(
        candidates,
        window_days=window_days,
        max_horizon_days=max_horizon_days,
    )
    logger.info(
        "[POLYMARKET] 백필 후보=%d(만기 %d) 스냅숏일=%d 실패=%s 탈락=%s",
        len(candidates),
        sum(1 for candidate in candidates if candidate.expired),
        len(snapshots),
        dict(sorted(failures.items())),
        dict(sorted(rejected.items())),
    )
    return BackfillResult(
        snapshots=snapshots,
        candidates=len(candidates),
        expired_candidates=sum(1 for candidate in candidates if candidate.expired),
        history_failures=failures,
        rejected=rejected,
    )
