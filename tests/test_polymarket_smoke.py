"""실제 Gamma API를 호출하는 opt-in 스모크 테스트.

기본 실행(`python -m pytest -q`)에서는 건너뛴다. **운영 Lightsail은 출구 IP가
달라 한국 PC에서 열렸다는 사실이 서버 접근을 보장하지 않는다.** 수집을 켜기
전에 서버에서 한 번 돌려 읽기가 되는지 확인한다.

```bash
RUN_POLYMARKET_SMOKE=1 python -m pytest -q -m polymarket_smoke
```

확인 항목: `closed=false&limit=1` 읽기, `/markets` 응답 파싱, Yes/No 확률 범위.
인증이 없고 LLM을 거치지 않으므로 Neurons를 소비하지 않는다.
"""

import os

import pytest

from core.config import POLYMARKET_BASE_URL, POLYMARKET_TIMEOUT
from features.market_sentiment.polymarket import (
    PolymarketClient,
    _extract_records,
    parse_contracts,
)

pytestmark = [
    pytest.mark.polymarket_smoke,
    pytest.mark.skipif(
        os.environ.get("RUN_POLYMARKET_SMOKE") != "1",
        reason="RUN_POLYMARKET_SMOKE=1 이 아닐 때는 실제 API를 호출하지 않는다",
    ),
]


def test_gamma_keyset_endpoint_is_readable():
    client = PolymarketClient(
        base_url=POLYMARKET_BASE_URL,
        timeout=POLYMARKET_TIMEOUT,
    )

    payload = client._request({"closed": "false", "limit": 1})
    records = _extract_records(payload)

    assert records, f"keyset 응답이 비어 있습니다: {str(payload)[:200]}"


def test_open_contracts_parse_into_probability_range():
    client = PolymarketClient(
        base_url=POLYMARKET_BASE_URL,
        timeout=POLYMARKET_TIMEOUT,
    )

    payload = client._request({"closed": "false", "limit": 20})
    contracts = parse_contracts(_extract_records(payload))

    # 20건 중 이진 Yes/No가 하나도 없으면 파서나 응답 형식을 다시 봐야 한다.
    assert contracts, "이진 Yes/No 계약을 하나도 읽지 못했습니다"
    assert all(0.0 <= contract.yes_price <= 1.0 for contract in contracts)
    assert all(contract.condition_id for contract in contracts)
