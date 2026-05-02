import asyncio
import html

from telegram import Update
from telegram.ext import ContextTypes

from handlers.core import build_view_result_keyboard, get_services


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await handle_view_show(update, context)
        return

    command = args[0].lower()
    if command == "show":
        await handle_view_show(update, context)
    elif command == "set":
        await handle_view_set(update, context, " ".join(args[1:]).strip())
    elif command == "run":
        await run_saved_view(update, context)
    elif command == "clear":
        await handle_view_clear(update, context)
    else:
        await handle_view_run(update, context, " ".join(args).strip(), temporary=True)


async def handle_view_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    view = services.market_view_store.get_view()
    last_result = services.market_view_store.get_last_result()

    view_text = html.escape(view) if view else "저장된 시장 뷰 없음"
    if last_result:
        generated_at = html.escape(str(last_result.get("generated_at") or ""))
        summary = html.escape(str(last_result.get("summary") or "요약 없음"))
        last_text = f"- 마지막 실행: {generated_at}\n- 요약: {summary}"
    else:
        last_text = "- 최근 분석 없음"

    await update.message.reply_text(
        "<b>시장 뷰</b>\n"
        f"{view_text}\n\n"
        "<b>최근 분석</b>\n"
        f"{last_text}\n\n"
        "<b>명령</b>\n"
        "/view show\n"
        "/view set 시장뷰내용\n"
        "/view run\n"
        "/view clear",
        parse_mode="HTML",
    )


async def handle_view_set(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
) -> None:
    if not market_view:
        await update.message.reply_text("사용법: /view set 시장뷰내용")
        return

    services = get_services(context)
    await asyncio.to_thread(services.market_view_store.set_view, market_view)
    await update.message.reply_text("시장 뷰를 저장했습니다.\n/view run 으로 분석을 실행하세요.")


async def handle_view_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    await asyncio.to_thread(services.market_view_store.clear_view)
    services.pending_store.clear()
    await update.message.reply_text("시장 뷰를 삭제했습니다. 워치리스트는 변경하지 않았습니다.")


async def run_saved_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    market_view = services.market_view_store.get_view()
    if not market_view:
        await update.message.reply_text(
            "저장된 시장 뷰가 없습니다.\n/view set 시장뷰내용 으로 먼저 저장하세요."
        )
        return
    await handle_view_run(update, context, market_view)


async def handle_view_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_view: str,
    temporary: bool = False,
) -> None:
    if not market_view:
        await update.message.reply_text("사용법: /view set 시장뷰내용")
        return

    services = get_services(context)
    status_message = await update.message.reply_text("전체 시장 뉴스 기준으로 시장 뷰 분석 중...")
    try:
        result = await services.market_view_analysis.run(market_view, temporary=temporary)
    except Exception as e:
        await status_message.edit_text(f"분석 실패: {html.escape(str(e))}", parse_mode="HTML")
        return

    if result.has_changes and result.uid:
        await status_message.edit_text(
            result.text,
            parse_mode="HTML",
            reply_markup=build_view_result_keyboard(result.uid),
        )
    else:
        await status_message.edit_text(result.text, parse_mode="HTML")


async def handle_view_apply(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    uid: str,
) -> None:
    services = get_services(context)
    text = await services.view_actions.apply(uid)
    await query.message.edit_text(text, parse_mode="HTML")


async def handle_view_cancel(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    uid: str,
) -> None:
    services = get_services(context)
    text = services.view_actions.cancel(uid)
    await query.message.edit_text(text)
