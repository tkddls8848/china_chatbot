"""국가별 뉴스 감성 차트 명령 구현.

차트는 기사별 감성을 매번 평균하지 않고 `MarketDigestStore`의 일별 확정값을
읽는다. 확정된 날(`final=True`)은 다시 계산하지 않으므로 같은 기간을 다시
조회해도 값이 변하지 않는다.
"""

import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from core.clock import today
from core.config import (
    MARKET_CHART_BACKFILL_DAYS_PER_REQUEST,
    MARKET_CHART_MARKETS,
    MARKET_CHART_LOOKBACK_DAYS,
    MARKET_CHART_MIN_ARTICLES,
    MARKET_CHART_MIN_DAYS,
    MARKET_DIGEST_ARTICLES_PER_DAY,
    MARKET_DIGEST_MAX_CALLS_PER_REQUEST,
    MARKET_DIGEST_MIN_ARTICLES,
    NEWS_MARKET_BACKFILL_QUERIES,
    POLYMARKET_PANEL_ENABLED,
)
from core.menu_status import set_menu_button_text
from core.workers import run_non_urgent
from features.market_sentiment.chart import market_label, render_market_chart
from news import backfill_market_digests
from state import MarketDigestStore, market_history_gaps

logger = logging.getLogger(__name__)

# 점 두 개짜리 패널은 추세가 아니라 선분이다. 이보다 적으면 그리지 않는다.
_PANEL_MIN_POINTS = 3
# 스냅숏은 08:35에 찍히므로 오전에는 최신값이 어제치다. 이틀 넘게 밀렸다면
# 수집이 멈춘 것이므로 낡은 선을 최신인 양 그리지 않는다.
_PANEL_MAX_STALE_DAYS = 2


def _spread_backfill_days(days: list, limit: int) -> list:
    """기간의 앞·중간·끝을 보존하면서 한 요청의 보충 연산량을 제한한다."""
    if len(days) <= limit:
        return days
    if limit <= 1:
        return [days[-1]]
    indexes = {
        round(index * (len(days) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [days[index] for index in sorted(indexes)]


async def _consensus_panel_series(context, days: int) -> list[dict] | None:
    """하단 패널에 그릴 24시간 거시 위험선호 변화. 자격 미달이면 None.

    이 함수가 None을 돌려주면 `/market`은 예전 그대로의 2패널 차트를 만든다.
    섀도 기간에는 `POLYMARKET_PANEL_ENABLED=false`라 항상 그 경로를 탄다.
    수집이 끊겼거나 표본이 얇을 때도 마찬가지다 — 외부 참고선 하나 때문에
    기존 감성 차트가 흔들리면 안 된다.
    """
    if not POLYMARKET_PANEL_ENABLED:
        return None
    store = context.bot_data.get("polymarket_store")
    if store is None:
        return None
    try:
        changes = await store.daily_changes(days)
        if len(changes) < _PANEL_MIN_POINTS:
            return None
        latest = date.fromisoformat(str(changes[-1]["date"]))
    except Exception:
        logger.warning("[POLYMARKET] 컨센서스 조회 실패, 패널 없이 진행합니다.", exc_info=True)
        return None
    if latest < today() - timedelta(days=_PANEL_MAX_STALE_DAYS):
        return None
    return changes


async def _set_market_status(message, callback_data: str, status, text: str) -> None:
    if callback_data:
        await set_menu_button_text(message, callback_data, text)
    elif status is not None:
        await status.edit_text(text)


async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send country/market news sentiment ranking and trend chart."""
    message = update.effective_message
    if message is None:
        return
    args = context.args or []
    days = MARKET_CHART_LOOKBACK_DAYS
    if args:
        try:
            days = int(args[0])
        except ValueError:
            await message.reply_text("사용법: /market [1-30일]")
            return
    if not 1 <= days <= 30:
        await message.reply_text("조회 기간은 1~30일로 지정해 주세요.")
        return

    store: MarketDigestStore | None = context.bot_data.get("market_digest_store")
    if store is None:
        await message.reply_text("시장 감성 캐시를 아직 준비하지 못했습니다.")
        return
    required_markets = set(MARKET_CHART_MARKETS)
    markets = await store.series(required_markets, days)
    gaps = market_history_gaps(
        markets,
        required_markets,
        MARKET_CHART_MIN_ARTICLES,
        min(days, MARKET_CHART_MIN_DAYS),
        MARKET_DIGEST_MIN_ARTICLES,
    )
    missing_days = await store.missing_digest_days(required_markets, days)
    backfill_days = {
        market: _spread_backfill_days(
            missing,
            MARKET_CHART_BACKFILL_DAYS_PER_REQUEST,
        )
        for market, missing in missing_days.items()
    }
    backfill_markets = {
        market for market, market_days in backfill_days.items() if market_days
    }
    needs_backfill = bool(backfill_markets)
    query = getattr(update, "callback_query", None)
    callback_data = str(getattr(query, "data", ""))
    if not callback_data.startswith("nav:market:"):
        callback_data = ""
    status = None
    if callback_data:
        await _set_market_status(message, callback_data, None, "◐ 데이터 점검 중")
    else:
        status = await message.reply_text(
            "차트용 일별 시장 감성을 점검하는 중입니다..."
        )
    try:
        if needs_backfill:
            analyzer = context.bot_data.get("market_digest_analyzer")
            semaphore = context.bot_data.get("market_digest_semaphore")
            if analyzer is None or semaphore is None:
                await _set_market_status(
                    message,
                    callback_data,
                    status,
                    "⚠️ 분석기 준비 안 됨",
                )
                return
            await _set_market_status(
                message,
                callback_data,
                status,
                "◓ 과거 뉴스 분석 중",
            )
            await backfill_market_digests(
                store,
                analyzer,
                semaphore,
                backfill_markets,
                NEWS_MARKET_BACKFILL_QUERIES,
                backfill_days,
                articles_per_day=MARKET_DIGEST_ARTICLES_PER_DAY,
                min_articles=MARKET_DIGEST_MIN_ARTICLES,
                max_calls=MARKET_DIGEST_MAX_CALLS_PER_REQUEST,
            )
            markets = await store.series(required_markets, days)
            gaps = market_history_gaps(
                markets,
                required_markets,
                MARKET_CHART_MIN_ARTICLES,
                min(days, MARKET_CHART_MIN_DAYS),
                MARKET_DIGEST_MIN_ARTICLES,
            )
        ready_markets = {market: stats for market, stats in markets.items() if market not in gaps}
        if len(ready_markets) < 2:
            detail = ", ".join(f"{market}: {reason}" for market, reason in sorted(gaps.items()))
            if callback_data:
                await _set_market_status(
                    message,
                    callback_data,
                    status,
                    "⚠️ 데이터 부족",
                )
            else:
                await status.edit_text(
                    "차트를 그릴 만큼 신뢰할 수 있는 국가별 시계열을 확보하지 못했습니다.\n"
                    f"부족 항목: {detail}\n"
                    "불완전한 선이나 단일 점 차트는 만들지 않았습니다. 잠시 뒤 다시 시도해 주세요."
                )
            return
        await _set_market_status(
            message,
            callback_data,
            status,
            "◑ 차트 생성 중",
        )
        consensus = await _consensus_panel_series(context, days)
        image = await run_non_urgent(
            render_market_chart, ready_markets, days, consensus
        )
        ranking = " | ".join(
            f"{market_label(market)} {stats['avg_sentiment']:+.2f} ({stats['count']})"
            for market, stats in sorted(ready_markets.items(), key=lambda item: item[1]["avg_sentiment"], reverse=True)
        )
        # 하루 평균 표본 수를 함께 노출한다. 표본이 얕으면 선이 출렁이므로
        # 값만 보여 주면 신뢰도를 오해하기 쉽다.
        sample_note = ""
        day_counts = [
            point["count"]
            for stats in ready_markets.values()
            for point in stats["daily"]
        ]
        if day_counts:
            sample_note = f"\n하루 평균 표본 {sum(day_counts) / len(day_counts):.0f}건"
        # 하단 패널은 국가별 점수와 축이 다른 외부 참고선이다. 순위·점수에
        # 섞이지 않았다는 사실을 캡션에서도 분명히 해 둔다.
        consensus_note = (
            "\n하단 패널은 Polymarket 거시 위험선호 확률변화(pp)로, 위 점수·순위와 무관합니다."
            if consensus
            else ""
        )
        await message.reply_photo(
            photo=image,
            caption=(
                f"국가·증시별 뉴스 감성 — 최근 {days}일\n{ranking}{sample_note}\n\n"
                "점수는 하루치 헤드라인을 종합한 분위기 지표(-1~+1)이며 투자 조언이 아닙니다."
                f"{consensus_note}"
            ),
        )
        if callback_data:
            await set_menu_button_text(message, callback_data, f"{days}일")
        else:
            await status.delete()
    except Exception as exc:
        logger.exception("[MARKET] chart rendering failed")
        if callback_data:
            await _set_market_status(
                message,
                callback_data,
                status,
                "❌ 생성 실패",
            )
        else:
            await status.edit_text(f"시장 감성 차트를 만들지 못했습니다: {exc}")
