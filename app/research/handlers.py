import asyncio
import html
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.config import RESEARCH_REMOVE_RELEVANCE_THRESHOLD
from core.workers import run_non_urgent
from research.candidates import build_research_candidate_universe
from research.discovery import collect_extra_candidates
from llm.market_view import MarketViewError, MarketViewManager
from stocks import StockDatabase
from llm.translator import TranslationService
from watchlist.events import record_watchlist_event

logger = logging.getLogger(__name__)
_RESEARCH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")

TELEGRAM_MESSAGE_LIMIT = 4096


def _log_research_task_error(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("[RESEARCH] background analysis cancelled")
    except Exception:
        logger.exception("[RESEARCH] background analysis failed")


def build_research_result_keyboard(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("적용", callback_data=f"research_apply:{uid}"),
                InlineKeyboardButton("취소", callback_data=f"research_cancel:{uid}"),
            ]
        ]
    )


def _normalize_code(code: str) -> str:
    raw = str(code).strip()
    value = "".join(ch for ch in raw if ch.isdigit())
    if not value:
        return raw
    if len(value) <= 5:
        return value.zfill(5)
    return value.zfill(6)


def _collect_research_actions(
    result: dict[str, Any],
    watchlist: Dict[str, str],
    stock_db: StockDatabase,
) -> dict[str, list[dict[str, Any]]]:
    add_items: list[dict[str, Any]] = []
    remove_items: list[dict[str, Any]] = []
    seen_add: set[str] = set()
    seen_remove: set[str] = set()

    for item in result.get("actions", []):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"add", "keep", "remove", "watch"}:
            continue
        confidence = float(item.get("confidence") or 0)
        raw_relevance = item.get("relevance")
        relevance = None
        if raw_relevance is not None:
            try:
                relevance = min(1.0, max(0.0, float(raw_relevance)))
            except (TypeError, ValueError):
                relevance = None

        code = _normalize_code(str(item.get("ticker") or ""))
        if not code:
            continue

        # 현재 관심종목은 LLM이 keep/watch로 응답하더라도 마켓 뷰 관련도가
        # 기준 미만이면 삭제 후보로 승격한다. 실제 삭제는 사용자의 적용 승인 후 수행한다.
        low_relevance = (
            code in watchlist
            and relevance is not None
            and relevance < RESEARCH_REMOVE_RELEVANCE_THRESHOLD
        )
        if low_relevance:
            action = "remove"

        if action == "add":
            if code in watchlist or code in seen_add:
                continue
            name = (
                str(item.get("name") or "").strip()
                or stock_db.get_display_name(code)
                or code
            )
            add_items.append(
                {
                    "code": code,
                    "name": name,
                    "reason": str(item.get("reason") or "").strip(),
                    "confidence": confidence,
                    "relevance": relevance,
                    "bull_case": str(item.get("bull_case") or "").strip(),
                    "bear_case": str(item.get("bear_case") or "").strip(),
                }
            )
            seen_add.add(code)
        elif action == "remove":
            if code not in watchlist or code in seen_remove:
                continue
            reason = str(item.get("reason") or "").strip()
            if low_relevance and item.get("action") != "remove":
                threshold_reason = (
                    f"마켓 뷰 관련도 {relevance:.0%}가 삭제 기준 "
                    f"{RESEARCH_REMOVE_RELEVANCE_THRESHOLD:.0%} 미만"
                )
                reason = f"{threshold_reason}. {reason}" if reason else threshold_reason
            remove_items.append(
                {
                    "code": code,
                    "name": watchlist[code],
                    "reason": reason,
                    "confidence": confidence,
                    "relevance": relevance,
                    "bull_case": str(item.get("bull_case") or "").strip(),
                    "bear_case": str(item.get("bear_case") or "").strip(),
                }
            )
            seen_remove.add(code)

    return {"add": add_items, "remove": remove_items}


def _format_action_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        reason = html.escape(str(item.get("reason") or ""))
        code = html.escape(str(item["code"]))
        name = html.escape(str(item["name"]))
        confidence = float(item.get("confidence") or 0)
        relevance = item.get("relevance")
        scores = [f"판단 {confidence:.0%}"]
        if relevance is not None:
            scores.insert(0, f"관련도 {float(relevance):.0%}")
        suffix = f" - {reason}" if reason else ""
        lines.append(f"- {name} ({code}) [{' · '.join(scores)}]{suffix}")
        bull_case = str(item.get("bull_case") or "").strip()
        bear_case = str(item.get("bear_case") or "").strip()
        if bull_case:
            lines.append(f"  🐂 {html.escape(bull_case[:120])}")
        if bear_case:
            lines.append(f"  🐻 {html.escape(bear_case[:120])}")
    return "\n".join(lines) if lines else "- 없음"


def _format_research_result_message(
    result: dict[str, Any],
    pending: dict[str, list[dict[str, Any]]],
    news_count: int,
    candidate_count: int = 0,
    temporary: bool = False,
) -> str:
    title = "리서치 분석 결과"
    if temporary:
        title += " (임시 리서치)"

    summary = html.escape(result.get("summary") or "요약 없음")
    add_lines = _format_action_lines(pending["add"])
    remove_lines = _format_action_lines(pending["remove"])

    watch_lines = []
    keep_lines = []
    for item in result.get("actions", []):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"watch", "keep"}:
            continue
        code = html.escape(_normalize_code(str(item.get("ticker") or "")))
        name = html.escape(str(item.get("name") or code))
        reason = html.escape(str(item.get("reason") or ""))
        relevance = item.get("relevance")
        line = f"- {name} ({code})"
        if relevance is not None:
            line += f" [관련도 {float(relevance):.0%}]"
        if reason:
            line += f" - {reason}"
        if action == "watch":
            watch_lines.append(line)
        else:
            keep_lines.append(line)

    dropped = result.get("verification_dropped") or []
    dropped_lines = []
    for item in dropped[:5]:
        if not isinstance(item, dict):
            continue
        code = html.escape(_normalize_code(str(item.get("ticker") or "")))
        name = html.escape(str(item.get("name") or code))
        reason = html.escape(str(item.get("reason") or "")[:100])
        action_label = "추가" if item.get("action") == "add" else "제외"
        dropped_lines.append(f"- [{action_label} 기각] {name} ({code}) {reason}")

    risks = result.get("risks") or []
    risk_lines = "\n".join(f"- {html.escape(str(r))}" for r in risks[:5]) or "- 없음"
    verified_mark = " ✅검증됨" if result.get("verified") else ""
    text = (
        f"<b>{html.escape(title)}</b>{verified_mark}\n"
        f"분석 뉴스: {news_count}건 / 후보 universe: {candidate_count}개\n\n"
        f"<b>요약</b>\n{summary}\n\n"
        f"<b>추가 후보</b>\n{add_lines}\n\n"
        f"<b>제외 후보</b>\n{remove_lines}\n\n"
        f"<b>주목 종목</b>\n{chr(10).join(watch_lines[:5]) or '- 없음'}\n\n"
        f"<b>유지</b>\n{chr(10).join(keep_lines[:5]) or '- 없음'}\n\n"
        f"<b>리스크</b>\n{risk_lines}"
    )
    if dropped_lines:
        text += f"\n\n<b>검증에서 기각된 후보</b>\n{chr(10).join(dropped_lines)}"
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."
    return text


async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] command update has no effective message: %s", update)
        return

    args = context.args or []
    if not args:
        await _handle_research_show(update, context)
        return

    command = args[0].lower()
    if command == "show":
        await _handle_research_show(update, context)
    elif command == "set":
        await _handle_research_set(update, context, " ".join(args[1:]).strip())
    elif command == "run":
        mvm: MarketViewManager = context.bot_data["market_view_manager"]
        market_view = mvm.get_sight()
        if not market_view:
            await message.reply_text(
                "저장된 리서치 주제가 없습니다.\n/research set 리서치주제 으로 먼저 저장하세요."
            )
            return
        await _handle_research_run(update, context, market_view)
    elif command == "clear":
        await _handle_research_clear(update, context)
    else:
        await _handle_research_run(update, context, " ".join(args).strip(), temporary=True)


async def _handle_research_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] show update has no effective message: %s", update)
        return

    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    view = mvm.get_sight()
    last_result = mvm.get_last_result()

    view_text = html.escape(view) if view else "저장된 리서치 주제 없음"
    if last_result:
        generated_at = html.escape(str(last_result.get("generated_at") or ""))
        summary = html.escape(str(last_result.get("summary") or "요약 없음"))
        last_text = f"- 마지막 실행: {generated_at}\n- 요약: {summary}"
    else:
        last_text = "- 최근 분석 없음"

    await message.reply_text(
        "<b>리서치 주제</b>\n"
        f"{view_text}\n\n"
        "<b>최근 분석</b>\n"
        f"{last_text}\n\n"
        "<b>명령</b>\n"
        "/research show\n"
        "/research set 리서치주제\n"
        "/research run\n"
        "/research clear",
        parse_mode="HTML",
    )


async def _handle_research_set(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] set update has no effective message: %s", update)
        return

    if not market_view:
        await message.reply_text("사용법: /research set 리서치주제")
        return

    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    await asyncio.to_thread(mvm.set_sight, market_view)
    await message.reply_text(
        "리서치 주제를 저장했습니다.\n/research run 으로 분석을 실행하세요."
    )


async def _handle_research_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] clear update has no effective message: %s", update)
        return

    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    await asyncio.to_thread(mvm.clear_sight)
    context.bot_data["research_pending"] = {}
    await message.reply_text("리서치 주제를 삭제했습니다. 워치리스트는 변경하지 않았습니다.")


async def _handle_research_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
    temporary: bool = False,
) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] run update has no effective message: %s", update)
        return
    if not market_view:
        await message.reply_text("사용법: /research set 리서치주제")
        return

    tasks: set[asyncio.Task] = context.bot_data.setdefault("research_tasks", set())
    active_tasks = {task for task in tasks if not task.done()}
    if active_tasks:
        context.bot_data["research_tasks"] = active_tasks
        await message.reply_text("⏳ 이미 리서치 분석이 실행 중입니다. 완료 후 다시 요청해 주세요.")
        return

    task = asyncio.create_task(
        _run_research_job(update, context, market_view, temporary),
        name="research-analysis",
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    task.add_done_callback(_log_research_task_error)
    await message.reply_text("⏳ 리서치 분석을 백그라운드에서 시작했습니다. 완료되면 결과를 알려드립니다.")


async def _run_research_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
    temporary: bool = False,
) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("[RESEARCH] run update has no effective message: %s", update)
        return

    if not market_view:
        await message.reply_text("사용법: /research set 리서치주제")
        return

    wm = context.bot_data["watchlist_manager"]
    stock_db: StockDatabase = context.bot_data["stock_db"]
    analyzer = context.bot_data["market_view_analyzer"]
    mvm: MarketViewManager = context.bot_data["market_view_manager"]
    translator: TranslationService = context.bot_data["translator"]
    translate_semaphore: asyncio.Semaphore = context.bot_data["translate_semaphore"]
    collect_global_news = context.bot_data["research_news_collector"]

    watchlist = await wm.get_all()
    status_message = await message.reply_text("전체 시장 뉴스 기준으로 리서치 분석 중...")
    news_items = await collect_global_news(translator, translate_semaphore)
    if not news_items:
        await status_message.edit_text("최근 전체 시장 뉴스가 없어 분석을 실행하지 않았습니다.")
        return
    candidate_universe = build_research_candidate_universe(stock_db, watchlist, news_items, market_view)

    # 강세 섹터 구성종목·问财 스크리닝 후보를 코드 중복 없이 병합한다.
    quote_service = context.bot_data.get("quote_service")
    try:
        extra_candidates = await run_non_urgent(
            collect_extra_candidates, quote_service, stock_db, watchlist, market_view
        )
        existing_codes = {c["code"] for c in candidate_universe}
        candidate_universe.extend(
            c for c in extra_candidates if c["code"] not in existing_codes
        )
    except Exception as e:
        logger.warning("[RESEARCH] 추가 후보 수집 실패: %s", e)

    # 정량 스냅샷과 직전 분석 이력을 분석 입력에 주입한다(각각 최선 노력).
    quant_context = None
    if quote_service is not None and quote_service.enabled:
        try:
            quant_context = await run_non_urgent(
                quote_service.build_quant_context, watchlist
            )
        except Exception as e:
            logger.warning("[RESEARCH] 정량 컨텍스트 수집 실패: %s", e)
    previous_analyses = mvm.get_history_summaries()

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            _RESEARCH_EXECUTOR,
            analyzer.analyze,
            market_view,
            watchlist,
            news_items,
            candidate_universe,
            quant_context,
            previous_analyses,
        )
    except MarketViewError as e:
        logger.error("[RESEARCH] analysis failed: %s", e)
        await status_message.edit_text(f"분석 실패: {html.escape(str(e))}", parse_mode="HTML")
        return
    except Exception as e:
        logger.error("[RESEARCH] analysis error: %s", e)
        await status_message.edit_text(f"분석 실패: {html.escape(str(e))}", parse_mode="HTML")
        return

    pending = _collect_research_actions(result, watchlist, stock_db)
    if not temporary:
        await run_non_urgent(mvm.save_result, result)

    text = _format_research_result_message(
        result,
        pending,
        len(news_items),
        len(candidate_universe),
        temporary,
    )
    has_changes = bool(pending["add"] or pending["remove"])
    if not has_changes:
        await status_message.edit_text(
            text + "\n\n변경 적용 후보가 없습니다.",
            parse_mode="HTML",
        )
        return

    uid = uuid.uuid4().hex[:8]
    context.bot_data.setdefault("research_pending", {})[uid] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "market_view": market_view,
        "add": pending["add"],
        "remove": pending["remove"],
        "summary": result.get("summary") or "",
    }
    await status_message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=build_research_result_keyboard(uid),
    )


async def handle_research_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
) -> bool:
    if data.startswith("research_apply:"):
        await _handle_research_apply(query, context, data.split(":", 1)[1])
        return True
    if data.startswith("research_cancel:"):
        await _handle_research_cancel(query, context, data.split(":", 1)[1])
        return True
    return False


async def _handle_research_apply(query, context: ContextTypes.DEFAULT_TYPE, uid: str) -> None:
    pending_map = context.bot_data.setdefault("research_pending", {})
    pending = pending_map.pop(uid, None)
    if not pending:
        await query.message.edit_text("요청을 찾을 수 없습니다. /research run을 다시 실행하세요.")
        return

    wm = context.bot_data["watchlist_manager"]
    watchlist = await wm.get_all()
    added: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []

    for item in pending.get("remove", []):
        code = str(item.get("code") or "")
        if code in watchlist:
            name = await wm.remove(code)
            removed.append(f"{name or item.get('name') or code} ({code})")
            watchlist.pop(code, None)
            await record_watchlist_event(
                context.bot_data,
                "remove",
                code,
                name or str(item.get("name") or code),
                reason=str(item.get("reason") or "리서치 적용"),
            )
        else:
            skipped.append(f"{item.get('name') or code} ({code})")

    for item in pending.get("add", []):
        code = str(item.get("code") or "")
        if code in watchlist:
            skipped.append(f"{watchlist[code]} ({code})")
            continue
        name = str(item.get("name") or code)
        await wm.add(code, name)
        added.append(f"{name} ({code})")
        watchlist[code] = name
        await record_watchlist_event(
            context.bot_data,
            "add",
            code,
            name,
            reason=str(item.get("reason") or "리서치 적용"),
        )

    text = (
        "<b>리서치 변경 적용 완료</b>\n\n"
        f"<b>추가</b>\n{chr(10).join('- ' + html.escape(x) for x in added) or '- 없음'}\n\n"
        f"<b>삭제</b>\n{chr(10).join('- ' + html.escape(x) for x in removed) or '- 없음'}"
    )
    if skipped:
        text += f"\n\n<b>건너뜀</b>\n{chr(10).join('- ' + html.escape(x) for x in skipped)}"
    await query.message.edit_text(text, parse_mode="HTML")


async def _handle_research_cancel(query, context: ContextTypes.DEFAULT_TYPE, uid: str) -> None:
    context.bot_data.setdefault("research_pending", {}).pop(uid, None)
    await query.message.edit_text("리서치 변경 적용을 취소했습니다.")
