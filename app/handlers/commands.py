"""텔레그램 명령어/콜백 핸들러와 메뉴 구성."""

import html
import logging
from datetime import datetime, timedelta
from pathlib import Path

from telegram import MenuButtonCommands, Update
from telegram.error import NetworkError
from telegram.ext import Application, ContextTypes

from core.config import (
    HELP_TEXT,
    MARKET_CHART_BACKFILL_DAYS_PER_REQUEST,
    MARKET_CHART_MARKETS,
    MARKET_CHART_LOOKBACK_DAYS,
    MARKET_CHART_MIN_ARTICLES,
    MARKET_CHART_MIN_DAYS,
    NEWS_MARKET_BACKFILL_QUERIES,
    PREDICTION_LOG_FILE,
    TELEGRAM_CHAT_ID,
    VIEW_LOOKBACK_DAYS,
)
from news import backfill_market_history
from news.utils import normalize_stock_code
from state import (
    NewsLog,
    PredictionLog,
    aggregate_market_sentiment,
    aggregate_stock_views,
    market_history_gaps,
)
from handlers.market_chart import market_label, render_market_chart
from handlers.menu_status import set_menu_button_text
from handlers.navigation import (
    handle_menu_callback,
    main_menu,
    persistent_menu,
)
from state.scoring import (
    DEFAULT_HORIZONS,
    DEFAULT_THRESHOLD,
    format_result_lines,
    load_signals,
    score_signals,
)
# research는 이 모듈을 역방향(research.handlers → handlers.menu_status →
# handlers/__init__ → 이 모듈)으로 임포트하므로, 순환을 피해 사용 지점에서
# 지연 임포트한다.
from stocks import StockDatabase
from core.system_control import SystemControlManager
from core.workers import run_non_urgent
from watchlist import handle_watchlist_callback

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


# ── 명령어 핸들러 ─────────────────────────────────────

async def cmd_stockdb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    stock_db: StockDatabase = context.bot_data["stock_db"]
    args = context.args or []
    command = args[0].lower() if args else ""

    if command == "build":
        status = await message.reply_text("종목 DB 빌드 중...")
        try:
            await run_non_urgent(stock_db.build)
            total = len(stock_db.get_all())
            await status.edit_text(f"종목 DB 빌드 완료: {total:,}종목")
        except Exception as e:
            logger.exception("[StockDB] build failed")
            await status.edit_text(f"빌드 실패: {e}")
        return

    await message.reply_text(
        "<b>stockdb 명령어</b>\n\n"
        "/stockdb build — 종목 코드·이름 목록 갱신",
        parse_mode="HTML",
    )


def _format_system_status(system: SystemControlManager, source_lines: list[str] | None = None) -> str:
    if system.gpu_enabled:
        gpu_line = (
            f"GPU 가속: <b>켜짐</b> "
            f"({SystemControlManager.describe(system.num_gpu)}, num_gpu={system.num_gpu})"
        )
    else:
        gpu_line = (
            f"GPU 가속: <b>꺼짐</b> (CPU 전용, "
            f"켜면 {SystemControlManager.describe(system.gpu_on_value)})"
        )
    sources_part = ""
    if source_lines:
        sources_part = "\n\n<b>전역 뉴스 소스</b>\n" + "\n".join(
            f"  {line}" for line in source_lines
        )
    return (
        "<b>시스템 상태</b>\n\n"
        f"{gpu_line}"
        f"{sources_part}\n\n"
        "제어:\n"
        "  /system gpu on — GPU 가속 켜기(자동)\n"
        "  /system gpu off — CPU 전용\n"
        "  /system gpu 레이어수 — 오프로딩 레이어 수 지정"
    )


async def cmd_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    system: SystemControlManager = context.bot_data["system_control"]
    args = context.args or []
    command = args[0].lower() if args else ""
    feature_registry = context.bot_data.get("feature_registry")

    if command == "features":
        lines = (
            feature_registry.catalog_lines()
            if feature_registry is not None
            else ["기능 레지스트리가 준비되지 않았습니다."]
        )
        await message.reply_text(
            "<b>기능 카탈로그</b>\n" + "\n".join(f"  {line}" for line in lines),
            parse_mode="HTML",
        )
        return

    if command == "gpu":
        value = args[1].lower() if len(args) > 1 else ""
        if value in ("on", "off"):
            system.set_gpu(value == "on")
        elif value.isdigit():
            system.set_gpu_layers(int(value))
        elif value == "":
            await message.reply_text(
                "사용법: /system gpu on | off | <레이어수>", parse_mode="HTML"
            )
            return
        else:
            await message.reply_text(
                "GPU 인자는 on, off 또는 0 이상의 정수여야 합니다.", parse_mode="HTML"
            )
            return
        logger.info("[System] GPU 설정 변경: num_gpu=%d", system.num_gpu)
    elif command:
        await message.reply_text(
            "알 수 없는 항목입니다. 사용법: /system [features|gpu on|off|<레이어수>]",
            parse_mode="HTML",
        )
        return

    registry = context.bot_data.get("news_registry")
    source_lines = registry.status_lines() if registry is not None else None
    await message.reply_text(
        _format_system_status(system, source_lines), parse_mode="HTML"
    )


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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    registry = context.bot_data.get("feature_registry")
    help_text = registry.help_text() if registry is not None else HELP_TEXT
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=persistent_menu(registry),
    )
    await update.message.reply_text(
        "원하는 기능을 선택하세요.",
        reply_markup=main_menu(registry),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def _answer_callback_safely(query) -> None:
    try:
        await query.answer()
    except NetworkError as exc:
        # A callback acknowledgement is best-effort. Telegram may have accepted
        # it even when the response times out, so keep processing the action.
        logger.warning("[TELEGRAM] 버튼 응답 확인 실패(동작은 계속): %s", exc)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _answer_callback_safely(query)
    data = query.data
    registry = context.bot_data.get("feature_registry")
    if registry is not None:
        if data.startswith("research_") and not registry.is_enabled("research"):
            await query.edit_message_text("리서치 기능이 비활성화되어 있습니다.")
            return
        if (
            data.startswith(("add_", "remove:", "close"))
            and not registry.is_enabled("watchlist")
        ):
            await query.edit_message_text("관심종목 기능이 비활성화되어 있습니다.")
            return

    if await handle_menu_callback(update, context, data):
        return

    from research import handle_research_callback

    if await handle_research_callback(query, context, data):
        return

    if await handle_watchlist_callback(query, context, data):
        return


async def configure_telegram_menu(app: Application) -> None:
    registry = app.bot_data.get("feature_registry")
    commands = registry.telegram_commands() if registry is not None else []
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="⌨️ 봇 재시작에 맞춰 하단 메뉴를 갱신했습니다.",
            reply_markup=persistent_menu(registry),
        )
    except Exception:
        logger.warning("Telegram 하단 메뉴 자동 갱신 실패", exc_info=True)
    logger.info("Telegram Menu 버튼 명령어 등록 완료: %s", [cmd.command for cmd in commands])
