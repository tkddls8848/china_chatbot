"""지난 30일 시세를 소급 수집해 Polymarket 승격 게이트를 지금 판정한다.

```powershell
.\venv\Scripts\python.exe app\polymarket_backfill.py
```

봇을 세우거나 `POLYMARKET_ENABLED`를 켤 필요가 없다. 읽기 전용이고 LLM을 거치지
않아 Neurons를 쓰지 않으며, 결과는 `data/market_sentiment/polymarket_backfill.json`
에만 쓴다(라이브 스냅숏 파일은 건드리지 않는다). 매번 다시 만들므로 여러 번
돌려도 값이 겹쳐 쌓이지 않는다.

판정 근거의 한계는 `polymarket_history.py` 첫머리에 적혀 있다. 요약하면 유동성·
호가는 조회 시점 값 하나뿐이고, median spread는 오늘 선정분으로만 계산되며,
수집 job의 가동률은 여기서 확인되지 않는다.
"""

import asyncio
import logging
import os
import sys

from core.config import (
    POLYMARKET_BACKFILL_FILE,
    POLYMARKET_BASE_URL,
    POLYMARKET_CLOB_URL,
    POLYMARKET_MAX_HORIZON_DAYS,
    POLYMARKET_MAX_SPREAD,
    POLYMARKET_MIN_LIQUIDITY,
    POLYMARKET_MIN_VOLUME,
    POLYMARKET_PROXY_URL,
    POLYMARKET_RETENTION_DAYS,
    POLYMARKET_TIMEOUT,
)
from features.market_sentiment.polymarket import PolymarketClient, PolymarketError
from features.market_sentiment.polymarket_history import (
    BACKFILL_CAVEATS,
    PolymarketHistoryClient,
    run_backfill,
)
from features.market_sentiment.polymarket_proxy import build_polymarket_session
from state import PROMOTION_WINDOW_DAYS, PolymarketConsensusStore

_LABELS = {
    "snapshot_days": "성공 스냅숏(일)",
    "delta_days": "유효 일별 변화(일)",
    "dense_day_ratio": "공통 이벤트 3개 이상 비율",
    "theme_count": "독립 theme(개)",
    "top_theme_contribution": "최대 theme 기여도",
    "median_spread": "median spread",
}
# 승격 게이트의 평가 창(PROMOTION_WINDOW_DAYS)에 고정한다. POLYMARKET_RETENTION_DAYS는
# 라이브 스토어가 얼마나 오래 보관하는지(차트용, /polymarket 기간 옵션)를 정할 뿐이고
# 게이트 임계값(_MIN_SNAPSHOT_DAYS=24 등)은 30일 창을 전제로 정했다 — 둘을 묶으면
# 보존 기간을 늘릴 때마다 게이트 판정창까지 조용히 늘어난다.
_WINDOW_DAYS = PROMOTION_WINDOW_DAYS


async def _store_snapshots(snapshots) -> int:
    # 매번 처음부터 다시 쓴다. 같은 날을 두 번 저장하지 않는 store 규칙 때문에
    # 이전 실행이 남아 있으면 새 값이 조용히 무시된다.
    #
    # 그렇다고 결과 파일을 먼저 지우지는 않는다. 중간에 실패하면 새 판정도 없고
    # 지난 판정도 없는 상태가 된다. 옆 파일에 끝까지 쓴 뒤 마지막에 교체한다.
    staging = POLYMARKET_BACKFILL_FILE.with_name(
        f"{POLYMARKET_BACKFILL_FILE.name}.staging"
    )
    staging.unlink(missing_ok=True)
    store = PolymarketConsensusStore(staging, retention_days=POLYMARKET_RETENTION_DAYS)
    stored = 0
    try:
        for day in sorted(snapshots):
            if await store.put_snapshot(day, snapshots[day]):
                stored += 1
        if not stored:
            return 0
        report = await store.promotion_report(window_days=_WINDOW_DAYS)
        os.replace(staging, POLYMARKET_BACKFILL_FILE)
    finally:
        staging.unlink(missing_ok=True)
    _print_report(report)
    return stored


def _print_report(report: dict) -> None:
    print()
    print(f"■ 승격 게이트 (백필 {report['window_days']}일)")
    for key, item in report["criteria"].items():
        mark = "PASS" if item["passed"] else "FAIL"
        note = BACKFILL_CAVEATS.get(key, "")
        line = (
            f"  [{mark}] {_LABELS.get(key, key)}: "
            f"{item['value']} (기준 {item['threshold']})"
        )
        print(f"{line}  ※ {note}" if note else line)
    print()
    print(
        "모든 항목 통과. 남은 확인은 수집 job 가동률뿐이다"
        " — `/system polymarket`에서 나란히 본다."
        if report["passed"]
        else "미달 항목이 있다. 라이브 30일을 더 기다려도 같은 항목이 통과할 근거는 없다."
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = build_polymarket_session(POLYMARKET_PROXY_URL)
    client = PolymarketClient(
        base_url=POLYMARKET_BASE_URL, timeout=POLYMARKET_TIMEOUT, session=session
    )
    history_client = PolymarketHistoryClient(
        base_url=POLYMARKET_CLOB_URL,
        timeout=POLYMARKET_TIMEOUT,
        session=session,
    )

    try:
        result = run_backfill(
            client,
            history_client,
            min_volume=POLYMARKET_MIN_VOLUME,
            min_liquidity=POLYMARKET_MIN_LIQUIDITY,
            max_spread=POLYMARKET_MAX_SPREAD,
            max_horizon_days=POLYMARKET_MAX_HORIZON_DAYS,
            window_days=_WINDOW_DAYS,
        )
    except PolymarketError as error:
        print(f"수집 실패: {error}", file=sys.stderr)
        return 1

    print()
    print(f"■ 후보 계약 {result.candidates}건 (만기 도래분 {result.expired_candidates}건 포함)")
    print(f"■ 탈락 사유: {dict(sorted(result.rejected.items())) or '없음'}")
    print(f"■ 이력 조회 실패: {dict(sorted(result.history_failures.items())) or '없음'}")

    if not result.snapshots:
        print("스냅숏을 한 날도 만들지 못했다. 위 사유를 먼저 본다.", file=sys.stderr)
        return 1

    stored = asyncio.run(_store_snapshots(result.snapshots))
    if not stored:
        print(
            "한 날도 저장하지 못했다. 지난 판정 파일은 그대로 두었다.",
            file=sys.stderr,
        )
        return 1
    print(f"\n{POLYMARKET_BACKFILL_FILE} 에 {stored}일치를 기록했다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
