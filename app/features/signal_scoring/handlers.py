"""종목 감성 뷰·신호 성과 명령 구현."""

import html
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from core.config import PREDICTION_LOG_FILE, VIEW_LOOKBACK_DAYS
from core.workers import run_non_urgent
from news.utils import normalize_stock_code
from state import PredictionLog, aggregate_stock_views
from state.scoring import (
    DEFAULT_HORIZONS,
    DEFAULT_THRESHOLD,
    format_result_lines,
    load_signals,
    score_signals,
)
from stocks import StockDatabase

logger = logging.getLogger(__name__)

_VERDICT_LABELS = {
    "up": "🟢 상승 우위",
    "down": "🔴 하락 우위",
    "neutral": "⚪ 중립",
}


def _view_footer() -> str:
    return (
        f"\n최근 {VIEW_LOOKBACK_DAYS}일 뉴스 감성 집계 기반 참고 뷰이며 "
        "예측·투자 조언이 아닙니다."
    )


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """뉴스 감성 신호 집계로 종목별 상승/중립/하락 참고 뷰를 표시한다.

    규칙 기반(평균 감성 임계값)이며 LLM을 추가로 호출하지 않는다.
    """
    message = update.effective_message
    if message is None:
        return
    prediction_log: PredictionLog | None = context.bot_data.get("prediction_log")
    if prediction_log is None:
        await message.reply_text("감성 신호 기록이 비활성화되어 있습니다.")
        return

    watchlist = await context.bot_data["watchlist_manager"].get_all()
    entries = await prediction_log.snapshot(VIEW_LOOKBACK_DAYS)
    args = context.args or []

    # /view 종목코드 — 단일 종목 상세(관심종목이 아니어도 조회 가능)
    if args:
        code = normalize_stock_code(args[0])
        stock_db: StockDatabase = context.bot_data["stock_db"]
        name = watchlist.get(code) or stock_db.get_display_name(code) or code
        view = aggregate_stock_views(entries, {code: name}).get(code)
        if view is None:
            await message.reply_text(
                f"{name} ({code}): 최근 {VIEW_LOOKBACK_DAYS}일 감성 신호가 없습니다."
            )
            return
        lines = [
            f"<b>{html.escape(name)} ({code}) 감성 뷰</b>",
            f"{_VERDICT_LABELS[view['verdict']]} · "
            f"평균 감성 {view['avg_sentiment']:+.2f} · 뉴스 {view['count']}건",
            "",
            "<b>근거 뉴스</b>",
        ]
        lines.extend(
            f"  • ({item['sentiment']:+.1f}) {html.escape(item['title'])}"
            for item in view["recent"]
        )
        lines.append(_view_footer())
        await message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # /view — 관심종목 전체 요약
    if not watchlist:
        await message.reply_text("관심종목이 없습니다.\n/add 종목코드 로 추가하세요.")
        return
    views = aggregate_stock_views(entries, watchlist)
    lines = [f"<b>관심종목 감성 뷰 (최근 {VIEW_LOOKBACK_DAYS}일)</b>", ""]
    for code, name in watchlist.items():
        view = views.get(code)
        if view is None:
            lines.append(f"  • {html.escape(name)} ({code}) — 신호 없음")
        else:
            lines.append(
                f"  • {html.escape(name)} ({code}) {_VERDICT_LABELS[view['verdict']]}"
                f" ({view['avg_sentiment']:+.2f}, {view['count']}건)"
            )
    lines.append(_view_footer())
    await message.reply_text("\n".join(lines), parse_mode="HTML")


def _score_report(log_path: Path, label: str) -> str:
    """신호 로드 → 시세 대조 채점 → HTML 리포트(블로킹, to_thread에서 실행)."""
    signals, neutral = load_signals(log_path, DEFAULT_THRESHOLD)
    if not signals:
        return (
            f"{label} 로그에 채점할 신호가 없습니다 "
            f"(중립 제외 {neutral}건, threshold={DEFAULT_THRESHOLD})."
        )
    up_count = sum(1 for s in signals if s["up"])
    results = score_signals(signals, DEFAULT_HORIZONS)
    table = "\n".join(format_result_lines(results, DEFAULT_HORIZONS))
    return (
        f"<b>감성 신호 적중률 ({label} 로그)</b>\n\n"
        f"신호 {len(signals)}건 (상승 {up_count} / 하락 {len(signals) - up_count}, "
        f"중립 제외 {neutral}건)\n\n"
        f"<pre>{html.escape(table)}</pre>\n\n"
        "적중률이 max(base, 1-base)를 지속 상회해야 신호에 정보가 있습니다. "
        "예측·투자 조언이 아닙니다."
    )


async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """운영 감성 신호를 실제 주가 방향과 대조해 적중률을 표시한다."""
    message = update.effective_message
    if message is None:
        return
    args = context.args or []
    if args:
        await message.reply_text("사용법: /score")
        return
    label, log_path = "운영", PREDICTION_LOG_FILE

    if not log_path.exists():
        await message.reply_text("운영 신호 로그가 없습니다.\n봇을 운영해 신호를 먼저 쌓아 주세요.")
        return

    status = await message.reply_text(f"{label} 신호 채점 중... (시세 조회)")
    try:
        report = await run_non_urgent(_score_report, log_path, label)
        await status.edit_text(report, parse_mode="HTML")
    except Exception as e:
        logger.exception("[SCORE] 채점 실패")
        await status.edit_text(f"채점 실패: {e}")
