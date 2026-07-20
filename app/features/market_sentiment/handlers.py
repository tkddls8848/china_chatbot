"""국가별 뉴스 감성 차트 명령 구현."""

import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from core.config import (
    MARKET_CHART_BACKFILL_DAYS_PER_REQUEST,
    MARKET_CHART_MARKETS,
    MARKET_CHART_LOOKBACK_DAYS,
    MARKET_CHART_MIN_ARTICLES,
    MARKET_CHART_MIN_DAYS,
    NEWS_MARKET_BACKFILL_QUERIES,
)
from core.menu_status import set_menu_button_text
from core.workers import run_non_urgent
from features.market_sentiment.chart import market_label, render_market_chart
from news import backfill_market_history
from state import NewsLog, aggregate_market_sentiment, market_history_gaps

logger = logging.getLogger(__name__)


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

    news_log: NewsLog | None = context.bot_data.get("news_log")
    if news_log is None:
        await message.reply_text("시장 감성 로그를 아직 준비하지 못했습니다.")
        return
    required_markets = set(MARKET_CHART_MARKETS)
    start_date = datetime.now().date() - timedelta(days=days - 1)
    entries = await news_log.snapshot_since_date(start_date)
    markets = aggregate_market_sentiment(entries, start_date=start_date)
    gaps = market_history_gaps(
        markets, required_markets, MARKET_CHART_MIN_ARTICLES, min(days, MARKET_CHART_MIN_DAYS)
    )
    missing_history_days = await news_log.missing_history_days(
        required_markets,
        days,
    )
    backfill_days = {
        market: _spread_backfill_days(
            missing,
            MARKET_CHART_BACKFILL_DAYS_PER_REQUEST,
        )
        for market, missing in missing_history_days.items()
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
            "차트용 과거 뉴스·감성 데이터를 점검하는 중입니다..."
        )
    try:
        if needs_backfill:
            translator = context.bot_data.get("translator")
            semaphore = context.bot_data.get("translate_semaphore")
            if translator is None or semaphore is None:
                await _set_market_status(
                    message,
                    callback_data,
                    status,
                    "⚠️ 수집기 준비 안 됨",
                )
                return
            await _set_market_status(
                message,
                callback_data,
                status,
                "◓ 과거 뉴스 분석 중",
            )
            await backfill_market_history(
                news_log,
                translator,
                semaphore,
                backfill_markets,
                NEWS_MARKET_BACKFILL_QUERIES,
                days,
                max_articles_per_day=1,
                days_by_market=backfill_days,
            )
            entries = await news_log.snapshot_since_date(start_date)
            markets = aggregate_market_sentiment(entries, start_date=start_date)
            gaps = market_history_gaps(
                markets, required_markets, MARKET_CHART_MIN_ARTICLES, min(days, MARKET_CHART_MIN_DAYS)
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
        image = await run_non_urgent(render_market_chart, ready_markets, days)
        ranking = " | ".join(
            f"{market_label(market)} {stats['avg_sentiment']:+.2f} ({stats['count']})"
            for market, stats in sorted(ready_markets.items(), key=lambda item: item[1]["avg_sentiment"], reverse=True)
        )
        await message.reply_photo(
            photo=image,
            caption=(
                f"국가·증시별 뉴스 감성 — 최근 {days}일\n{ranking}\n\n"
                "점수는 기사 단위 분위기 지표(-1~+1)이며 투자 조언이 아닙니다."
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
