"""Gamma keyset 클라이언트·파서 검증(1단계).

실제 API를 부르지 않는다. 배열 매핑, 확률 합계, 범위, 커서 순회, timeout,
429를 mock 응답으로 확인한다.
"""

import json

import pytest
import requests

from features.market_sentiment.polymarket import (
    PolymarketClient,
    PolymarketError,
    parse_contract,
    parse_contracts,
)


def _record(**overrides):
    record = {
        "conditionId": "0xabc",
        "question": "Will country A invade country B in 2026?",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.34", "0.66"]),
        "spread": 0.02,
        "volumeNum": 250000,
        "liquidityNum": 40000,
        "endDate": "2026-12-31T12:00:00Z",
        "active": True,
        "closed": False,
        "events": [{"id": "77", "slug": "geo-risk"}],
    }
    record.update(overrides)
    return record


class _Response:
    def __init__(self, payload=None, *, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(responses, **kwargs):
    return PolymarketClient(
        base_url="https://gamma-api.example",
        timeout=7,
        session=_Session(responses),
        sleep=lambda _seconds: None,
        **kwargs,
    )


# ── 배열 매핑·합계·범위 ───────────────────────────────

def test_json_string_outcomes_map_to_the_yes_leg():
    """Gamma는 outcomes·outcomePrices를 JSON 문자열로 준다."""
    contract = parse_contract(_record())

    assert contract.yes_price == pytest.approx(0.34)
    assert contract.condition_id == "0xabc"
    assert contract.event_id == "77"


def test_outcome_order_decides_the_price_not_position():
    """No가 먼저 오는 응답에서 위치로 읽으면 확률이 뒤집힌다."""
    contract = parse_contract(
        _record(
            outcomes=json.dumps(["No", "Yes"]),
            outcomePrices=json.dumps(["0.66", "0.34"]),
        )
    )

    assert contract.yes_price == pytest.approx(0.34)


def test_plain_list_outcomes_read_the_same_way():
    contract = parse_contract(
        _record(outcomes=["Yes", "No"], outcomePrices=[0.7, 0.3])
    )

    assert contract.yes_price == pytest.approx(0.7)


@pytest.mark.parametrize(
    "overrides",
    [
        # 합계가 1에서 크게 벗어나면 이진 시장이 아니다.
        {"outcomePrices": json.dumps(["0.34", "0.20"])},
        # 범위를 벗어난 확률.
        {"outcomePrices": json.dumps(["1.40", "-0.40"])},
        # 다지선다 시장.
        {
            "outcomes": json.dumps(["A", "B", "C"]),
            "outcomePrices": json.dumps(["0.3", "0.3", "0.4"]),
        },
        # Yes/No 라벨이 아닌 이진 시장.
        {"outcomes": json.dumps(["Up", "Down"])},
        # 개수가 어긋난 응답.
        {"outcomePrices": json.dumps(["0.34"])},
        # 숫자가 아닌 값.
        {"outcomePrices": json.dumps(["cheap", "expensive"])},
        # 식별자 없음.
        {"conditionId": ""},
    ],
)
def test_unusable_records_are_dropped_instead_of_guessed(overrides):
    assert parse_contract(_record(**overrides)) is None


def test_missing_spread_is_treated_as_worst_case():
    """spread가 없다고 0으로 채우면 호가 없는 계약이 최우량으로 둔갑한다."""
    contract = parse_contract(_record(spread=None))

    assert contract.spread == 1.0


def test_parse_contracts_skips_broken_records_without_failing_the_page():
    contracts = parse_contracts(
        [_record(), "not a dict", _record(conditionId="0xdef")]
    )

    assert [contract.condition_id for contract in contracts] == ["0xabc", "0xdef"]


def test_end_date_is_normalised_to_kst():
    contract = parse_contract(_record(endDate="2026-12-31T12:00:00Z"))

    assert contract.end_date.utcoffset().total_seconds() == 9 * 3600
    assert contract.end_date.hour == 21


# ── 커서 순회 ─────────────────────────────────────────

def test_keyset_pagination_follows_the_cursor():
    client = _client(
        [
            _Response({"data": [_record()], "next_cursor": "page2"}),
            _Response({"data": [_record(conditionId="0xdef")], "next_cursor": ""}),
        ]
    )

    contracts = client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert [contract.condition_id for contract in contracts] == ["0xabc", "0xdef"]
    calls = client._session.calls
    assert calls[0]["url"] == "https://gamma-api.example/markets/keyset"
    assert "next_cursor" not in calls[0]["params"]
    assert calls[1]["params"]["next_cursor"] == "page2"
    assert calls[0]["params"]["closed"] == "false"
    assert calls[0]["timeout"] == 7


def test_cursor_inside_pagination_envelope_is_honoured():
    client = _client(
        [
            _Response({"data": [_record()], "pagination": {"nextCursor": "page2"}}),
            _Response({"data": [], "pagination": {}}),
        ]
    )

    client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert client._session.calls[1]["params"]["next_cursor"] == "page2"


def test_repeated_cursor_stops_the_walk():
    """서버가 같은 커서를 되돌려 보내도 무한 루프에 빠지지 않는다."""
    client = _client(
        [
            _Response({"data": [_record()], "next_cursor": "same"}),
            _Response({"data": [_record(conditionId="0xdef")], "next_cursor": "same"}),
        ]
    )

    contracts = client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert len(client._session.calls) == 2
    assert len(contracts) == 2


def test_bare_list_response_ends_the_walk():
    client = _client([_Response([_record()])])

    contracts = client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert len(contracts) == 1
    assert len(client._session.calls) == 1


# ── timeout·429·422 ───────────────────────────────────

def test_timeout_is_retried_then_reported():
    client = _client(
        [
            requests.Timeout("read timed out"),
            requests.Timeout("read timed out"),
            requests.Timeout("read timed out"),
        ]
    )

    with pytest.raises(PolymarketError) as error:
        client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert error.value.reason == "timeout"
    assert error.value.retryable is True
    assert len(client._session.calls) == 3


def test_rate_limit_waits_the_retry_after_then_succeeds():
    slept = []
    client = PolymarketClient(
        base_url="https://gamma-api.example",
        timeout=7,
        session=_Session(
            [
                _Response(status_code=429, text="slow down", headers={"Retry-After": "3"}),
                _Response({"data": [_record()]}),
            ]
        ),
        sleep=slept.append,
    )

    contracts = client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert len(contracts) == 1
    assert slept == [3.0]


def test_rate_limit_retry_wait_is_capped():
    """Retry-After를 그대로 믿으면 job이 한 시간을 자고 있을 수 있다."""
    slept = []
    client = PolymarketClient(
        base_url="https://gamma-api.example",
        timeout=7,
        session=_Session(
            [
                _Response(status_code=429, text="", headers={"Retry-After": "3600"}),
                _Response({"data": [_record()]}),
            ]
        ),
        sleep=slept.append,
    )

    client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert slept == [10.0]


def test_client_error_is_not_retried():
    """422는 레거시 offset 순회의 신호다. 다시 걸어도 같은 답이 온다."""
    client = _client([_Response(status_code=422, text="offset too large")])

    with pytest.raises(PolymarketError) as error:
        client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert error.value.reason == "bad_request"
    assert error.value.status_code == 422
    assert len(client._session.calls) == 1


def test_server_error_is_retried():
    client = _client(
        [
            _Response(status_code=503, text="unavailable"),
            _Response({"data": [_record()]}),
        ]
    )

    contracts = client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert len(contracts) == 1
    assert len(client._session.calls) == 2


def test_non_json_response_is_reported_without_retry():
    client = _client([_Response(payload=None, status_code=200, text="<html>")])

    with pytest.raises(PolymarketError) as error:
        client.fetch_open_contracts(min_volume=10000, min_liquidity=1000)

    assert error.value.reason == "invalid_response"
    assert len(client._session.calls) == 1
