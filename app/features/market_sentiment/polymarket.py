"""Polymarket Gamma API 읽기 클라이언트와 계약 파서.

Gamma는 인증이 필요 없고 LLM을 거치지 않는다. 그래서 이 경로가 쓰는 추가
Neurons는 0/일이다. 여기서는 공개 시세만 읽으며 주문·체결 API는 건드리지 않는다.

**페이지네이션은 `/markets`와 offset으로 돈다.** `/markets/keyset`은 커서를
어떤 이름으로 넘겨도(`next_cursor`·`cursor`·`start_cursor`·`after`) 같은 첫
페이지를 되돌려 줘서 순회가 되지 않고, `limit`은 100에서 잘리며 offset은
422(`offset is not allowed on keyset endpoints`)다. 즉 keyset으로는 100건이
전부다. 레거시 `/markets`는 offset이 정상 동작한다.

만기가 먼 계약(2028 대선 등)이 거래량 상위를 덮고 있어 **`end_date_max`를
서버에 넘겨 지평 밖을 먼저 잘라 낸다.** 이 필터 없이 읽으면 첫 수백 건이
전부 `horizon_too_far`로 떨어져 선정이 0건이 된다. 정렬은 거래량 내림차순이라
뒤 페이지일수록 얇아진다 — 그래서 `_MAX_PAGES`에서 끊는다.

Gamma가 돌려주는 `outcomes`·`outcomePrices`·`clobTokenIds`는 **JSON 문자열**이다
(`'["Yes", "No"]'`). 리스트로 오는 응답도 있어 둘 다 같은 코드로 읽는다.
우리가 정한 형식이 아니라 외부 응답 형식이므로 이 모듈에서 한 번만 흡수하고,
바깥으로는 `PolymarketContract` 한 가지 모양만 내보낸다.

HTTP 요청·재시도·오류 분류는 `_JsonEndpoint`에 모아 둔다. 과거 시세를 읽는
`polymarket_history.py`는 host도 경로도 다르지만 재시도 규칙은 같아야 해서
같은 base를 쓴다 — 재시도를 두 벌로 두면 한쪽만 고치는 날이 온다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

from core.clock import ensure_kst, now

logger = logging.getLogger(__name__)

# 한 번의 스냅숏에서 돌 최대 페이지 수. 지평 안 계약만 세어도 1,200건이 넘어
# 끝까지 도는 것은 의미가 없다. 거래량 내림차순이라 상위 1,000건이면 게이트를
# 통과하는 계약(실측 24건 / 20개 이벤트)이 모두 들어온다.
_MAX_PAGES = 10
_PAGE_SIZE = 100
# 429·5xx·timeout에만 재시도한다. 스냅숏은 하루 한 번이라 여기서 포기하면
# 그날 delta가 통째로 비므로 짧게 두 번까지 더 시도한다.
_MAX_ATTEMPTS = 3
_MAX_RETRY_AFTER_SECONDS = 10.0
_MAX_ERROR_DETAIL_CHARS = 200
# Yes/No 두 값의 합이 1에서 이만큼 벗어나면 이진 시장으로 읽지 않는다.
# 다지선다 시장의 자식 계약이 Yes/No처럼 보이는 응답을 걸러 낸다.
_PRICE_SUM_TOLERANCE = 0.05


class PolymarketError(RuntimeError):
    """Gamma 호출 실패. 재시도 가능 여부를 함께 담는다."""

    def __init__(
        self,
        reason: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after: float = 0.0,
        detail: str = "",
    ):
        self.reason = reason
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.detail = detail
        message = reason
        if status_code is not None:
            message = f"{message} (HTTP {status_code})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class PolymarketContract:
    """게이트·polarity 규칙이 읽는 이진 계약 1건.

    `event_id`는 같은 이벤트의 자식 계약(S&P 임계값 8개 등)을 하나로 축약할 때
    쓴다. 비어 있으면 축약 단계에서 `condition_id`를 이벤트로 취급한다.

    `yes_token_id`는 CLOB 과거 시세(`polymarket_history.py`)를 조회하는 키다.
    Gamma의 `conditionId`로는 시세 이력을 부를 수 없어 Yes 다리의 토큰 id를
    여기서 함께 들고 나온다. 일별 스냅숏 경로는 이 값을 쓰지 않는다.
    """

    condition_id: str
    event_id: str
    question: str
    yes_price: float
    spread: float
    volume: float
    liquidity: float
    end_date: datetime | None
    active: bool
    closed: bool
    yes_token_id: str = ""


def _truncate(text: Any, limit: int = _MAX_ERROR_DETAIL_CHARS) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _as_list(value: Any) -> list[Any] | None:
    """JSON 문자열이든 리스트든 같은 리스트로 읽는다."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN 제외


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return default


def _parse_end_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 만기 시각은 KST 기준 하루 경계와 비교하므로 앱 표준 타임존으로 맞춘다.
    return ensure_kst(parsed)


def _yes_leg(record: dict[str, Any]) -> tuple[int, float] | None:
    """Yes 결과의 (자리, 확률)을 뽑는다. 이진 Yes/No 시장이 아니면 None.

    자리를 함께 돌려주는 이유는 `clobTokenIds`가 `outcomes`와 같은 순서라서다.
    """
    outcomes = _as_list(record.get("outcomes"))
    prices = _as_list(record.get("outcomePrices"))
    if not outcomes or not prices or len(outcomes) != len(prices) or len(outcomes) != 2:
        return None

    labels = [str(item).strip().lower() for item in outcomes]
    if set(labels) != {"yes", "no"}:
        return None

    parsed = [_as_float(price) for price in prices]
    if any(price is None for price in parsed):
        return None
    if any(not 0.0 <= price <= 1.0 for price in parsed):
        return None
    if abs(sum(parsed) - 1.0) > _PRICE_SUM_TOLERANCE:
        return None
    index = labels.index("yes")
    return index, parsed[index]


def _token_id(record: dict[str, Any], index: int) -> str:
    """Yes 다리의 CLOB 토큰 id. 없으면 빈 문자열(과거 시세 조회만 못 한다)."""
    token_ids = _as_list(record.get("clobTokenIds"))
    if not token_ids or index >= len(token_ids):
        return ""
    return str(token_ids[index] or "").strip()


def _event_id(record: dict[str, Any]) -> str:
    events = record.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        if isinstance(first, dict):
            identifier = first.get("id") or first.get("slug")
            if identifier:
                return str(identifier)
    return ""


def parse_contract(record: Any) -> PolymarketContract | None:
    """Gamma 레코드 1건을 계약으로 바꾼다. 읽을 수 없으면 None."""
    if not isinstance(record, dict):
        return None
    condition_id = str(record.get("conditionId") or "").strip()
    question = str(record.get("question") or "").strip()
    if not condition_id or not question:
        return None
    leg = _yes_leg(record)
    if leg is None:
        return None
    yes_index, yes_price = leg
    return PolymarketContract(
        condition_id=condition_id,
        event_id=_event_id(record),
        question=question,
        yes_price=yes_price,
        # spread가 없는 응답은 게이트에서 떨어지도록 최악값(1.0)으로 둔다.
        # 0.0으로 채우면 호가가 없는 계약이 가장 좋은 계약으로 둔갑한다.
        spread=_as_float(record.get("spread")) or 1.0,
        volume=_as_float(record.get("volumeNum")) or 0.0,
        liquidity=_as_float(record.get("liquidityNum")) or 0.0,
        end_date=_parse_end_date(record.get("endDate")),
        active=_as_bool(record.get("active"), True),
        closed=_as_bool(record.get("closed"), False),
        yes_token_id=_token_id(record, yes_index),
    )


def parse_contracts(records: Iterable[Any]) -> list[PolymarketContract]:
    contracts = []
    for record in records:
        contract = parse_contract(record)
        if contract is not None:
            contracts.append(contract)
    return contracts


def _extract_records(payload: Any) -> list[Any]:
    """`/markets` 응답에서 시장 레코드를 꺼낸다. 이 엔드포인트는 배열을 돌려준다."""
    return payload if isinstance(payload, list) else []


def _horizon_cutoff(max_horizon_days: int) -> str:
    """서버에 넘길 만기 상한. Gamma는 UTC ISO 문자열로 받는다.

    `now()`는 KST aware라 그대로 포매팅하면 9시간을 UTC로 오기하게 된다.
    반드시 UTC로 변환한 뒤 찍는다.
    """
    cutoff = now() + timedelta(days=max(1, max_horizon_days))
    return _gamma_timestamp(cutoff)


def _days_ago_cutoff(days: int) -> str:
    """과거 쪽 만기 경계. 백필이 `end_date_min`으로 넘긴다."""
    return _gamma_timestamp(now() - timedelta(days=max(0, days)))


def _gamma_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _JsonEndpoint:
    """재시도와 오류 분류를 담은 읽기 전용 JSON 엔드포인트."""

    def __init__(
        self,
        *,
        url: str,
        timeout: float,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep

    @property
    def url(self) -> str:
        return self._url

    def _request(self, params: dict[str, Any]) -> Any:
        last_error: PolymarketError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._request_once(params)
            except PolymarketError as error:
                last_error = error
                if not error.retryable or attempt == _MAX_ATTEMPTS - 1:
                    break
                delay = min(error.retry_after, _MAX_RETRY_AFTER_SECONDS)
                if delay > 0:
                    self._sleep(delay)
        assert last_error is not None
        raise last_error

    def _request_once(self, params: dict[str, Any]) -> Any:
        try:
            response = self._session.get(
                self._url,
                params=params,
                timeout=self._timeout,
            )
        except requests.Timeout as error:
            raise self._fail("timeout", retryable=True, detail=str(error))
        except requests.RequestException as error:
            raise self._fail("connection", retryable=True, detail=str(error))

        status = getattr(response, "status_code", None)
        if status is not None and status >= 400:
            raise self._http_failure(response, status)

        try:
            return response.json()
        except ValueError as error:
            raise self._fail(
                "invalid_response",
                status_code=status,
                retryable=False,
                detail=f"response is not JSON: {error}",
            )

    def _http_failure(self, response: Any, status: int) -> PolymarketError:
        if status == 429:
            reason, retryable = "rate_limited", True
        elif status >= 500:
            reason, retryable = "server_error", True
        else:
            # 400/422 등 요청 형식 오류는 재시도해도 같은 결과다.
            reason, retryable = "bad_request", False
        return self._fail(
            reason,
            status_code=status,
            retryable=retryable,
            retry_after=_parse_retry_after(
                (getattr(response, "headers", None) or {}).get("Retry-After")
            ),
            detail=getattr(response, "text", "") or "",
        )

    @staticmethod
    def _fail(
        reason: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after: float = 0.0,
        detail: str = "",
    ) -> PolymarketError:
        error = PolymarketError(
            reason,
            status_code=status_code,
            retryable=retryable,
            retry_after=retry_after,
            detail=_truncate(detail),
        )
        logger.warning(
            "[POLYMARKET] result=%s status=%s detail=%s",
            reason,
            status_code if status_code is not None else "-",
            error.detail or "-",
        )
        return error


class PolymarketClient(_JsonEndpoint):
    """Gamma `/markets` 읽기 전용 클라이언트."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__(
            url=f"{base_url.rstrip('/')}/markets",
            timeout=timeout,
            session=session,
            sleep=sleep,
        )

    def fetch_open_contracts(
        self,
        *,
        min_volume: float,
        min_liquidity: float,
        max_horizon_days: int,
    ) -> list[PolymarketContract]:
        """열려 있는 이진 계약을 거래량 상위부터 읽어 온다.

        수량·지평 필터는 서버에도 넘겨 페이지를 아끼지만, 최종 판정은 규칙
        모듈의 게이트가 다시 한다(서버가 필터를 무시해도 값이 새지 않는다).
        """
        return self._walk(
            {
                "closed": "false",
                "active": "true",
                "volume_num_min": min_volume,
                "liquidity_num_min": min_liquidity,
                "end_date_max": _horizon_cutoff(max_horizon_days),
            }
        )

    def fetch_expired_contracts(
        self,
        *,
        min_volume: float,
        since_days: int,
    ) -> list[PolymarketContract]:
        """최근 `since_days` 안에 만기가 온 계약을 읽어 온다(백필 전용).

        일별 스냅숏 경로는 이 메서드를 쓰지 않는다. 과거를 재구성할 때만 필요한데,
        열린 계약만 모아 과거를 그리면 **살아남은 계약만 남는다** — 그 기간에
        만기로 사라진 계약이 통째로 빠져 짝이 끊기는 일이 없는 것처럼 보인다.

        **유동성·호가 필터를 넘기지 않는다.** 청산된 계약의 `liquidityNum`·
        `spread`는 결제 후 값이라 당시 유동성이 아니다. 거래량은 누적이라 만기
        뒤에도 남으므로 그것만 서버에 넘긴다.
        """
        return self._walk(
            {
                "closed": "true",
                "volume_num_min": min_volume,
                "end_date_min": _days_ago_cutoff(since_days),
                "end_date_max": _days_ago_cutoff(0),
            }
        )

    def _walk(self, params: dict[str, Any]) -> list[PolymarketContract]:
        """offset을 돌며 거래량 상위부터 계약을 모은다."""
        contracts: list[PolymarketContract] = []
        pages = 0
        while pages < _MAX_PAGES:
            payload = self._request(
                {
                    **params,
                    "limit": _PAGE_SIZE,
                    "offset": pages * _PAGE_SIZE,
                    # 거래량 내림차순. 앞 페이지일수록 게이트를 통과할 확률이 높다.
                    "order": "volumeNum",
                    "ascending": "false",
                }
            )
            pages += 1
            records = _extract_records(payload)
            contracts.extend(parse_contracts(records))
            if len(records) < _PAGE_SIZE:
                break
        logger.info("[POLYMARKET] pages=%d contracts=%d", pages, len(contracts))
        return contracts


def _parse_retry_after(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if seconds > 0 else 0.0
