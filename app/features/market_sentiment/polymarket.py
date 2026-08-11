"""Polymarket Gamma API 읽기 클라이언트와 계약 파서.

Gamma는 인증이 필요 없고 LLM을 거치지 않는다. 그래서 이 경로가 쓰는 추가
Neurons는 0/일이다. 여기서는 공개 시세만 읽으며 주문·체결 API는 건드리지 않는다.

**페이지네이션은 `/markets/keyset`과 cursor만 쓴다.** 레거시 `/markets`를 큰
offset으로 돌면 422가 나서 순회가 중간에 끊긴다. 커서가 더 이상 없거나 같은
커서가 반복되면 멈춘다(서버가 커서를 되돌려 보내도 무한 루프에 빠지지 않는다).

Gamma가 돌려주는 `outcomes`·`outcomePrices`는 **JSON 문자열**이다
(`'["Yes", "No"]'`). 리스트로 오는 응답도 있어 둘 다 같은 코드로 읽는다.
우리가 정한 형식이 아니라 외부 응답 형식이므로 이 모듈에서 한 번만 흡수하고,
바깥으로는 `PolymarketContract` 한 가지 모양만 내보낸다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

import requests

from core.clock import ensure_kst

logger = logging.getLogger(__name__)

# 한 번의 스냅숏에서 돌 최대 페이지 수. 게이트를 통과할 계약은 수십 건 규모라
# 이 상한에 닿을 일이 없다. 서버가 커서를 계속 내주는 병리적 상황에서만 걸린다.
_MAX_PAGES = 20
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


def _yes_price(record: dict[str, Any]) -> float | None:
    """Yes 결과의 확률을 뽑는다. 이진 Yes/No 시장이 아니면 None."""
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
    return parsed[labels.index("yes")]


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
    yes_price = _yes_price(record)
    if yes_price is None:
        return None
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
    )


def parse_contracts(records: Iterable[Any]) -> list[PolymarketContract]:
    contracts = []
    for record in records:
        contract = parse_contract(record)
        if contract is not None:
            contracts.append(contract)
    return contracts


def _extract_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


def _extract_cursor(payload: Any) -> str:
    """다음 페이지 커서를 뽑는다.

    envelope의 키 표기는 우리가 고정할 수 없으므로 알려진 자리만 순서대로 본다.
    첫 번째로 발견한 비어 있지 않은 문자열을 쓰고, 없으면 순회를 끝낸다.
    """
    if not isinstance(payload, dict):
        return ""
    pagination = payload.get("pagination")
    candidates = (
        payload.get("next_cursor"),
        payload.get("nextCursor"),
        pagination.get("next_cursor") if isinstance(pagination, dict) else None,
        pagination.get("nextCursor") if isinstance(pagination, dict) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


class PolymarketClient:
    """Gamma `/markets/keyset` 읽기 전용 클라이언트."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = f"{base_url.rstrip('/')}/markets/keyset"
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep

    @property
    def url(self) -> str:
        return self._url

    def fetch_open_contracts(
        self,
        *,
        min_volume: float,
        min_liquidity: float,
    ) -> list[PolymarketContract]:
        """열려 있는 이진 계약을 커서로 끝까지 읽어 온다.

        수량 필터는 서버에도 넘겨 페이지 수를 줄이지만, 최종 판정은 규칙
        모듈의 게이트가 다시 한다(서버가 필터를 무시해도 값이 새지 않는다).
        """
        contracts: list[PolymarketContract] = []
        seen_cursors: set[str] = set()
        cursor = ""
        pages = 0
        while pages < _MAX_PAGES:
            params: dict[str, Any] = {
                "closed": "false",
                "active": "true",
                "limit": _PAGE_SIZE,
                "volume_num_min": min_volume,
                "liquidity_num_min": min_liquidity,
            }
            if cursor:
                params["next_cursor"] = cursor
            payload = self._request(params)
            pages += 1
            records = _extract_records(payload)
            contracts.extend(parse_contracts(records))
            cursor = _extract_cursor(payload)
            if not records or not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        else:
            logger.warning(
                "[POLYMARKET] 페이지 상한 %d에 도달해 순회를 멈춥니다.", _MAX_PAGES
            )
        logger.info("[POLYMARKET] pages=%d contracts=%d", pages, len(contracts))
        return contracts

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
            # 422는 잘못된 순회 방식(레거시 offset)의 신호다. 재시도해도 같다.
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


def _parse_retry_after(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if seconds > 0 else 0.0
