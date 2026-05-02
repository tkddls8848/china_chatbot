from typing import Dict

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ── keyboard constants ────────────────────────────────────────────────────────

_BTN_ANALYZE = "📊 분석"
_BTN_VIEW    = "📰 시장뷰"
_BTN_LIST    = "📋 목록"
_BTN_ADD     = "🔍 추가"


def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(_BTN_ANALYZE), KeyboardButton(_BTN_VIEW),
          KeyboardButton(_BTN_LIST),    KeyboardButton(_BTN_ADD)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def build_list_keyboard(watchlist: Dict[str, str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {name} ({code})",
            callback_data=f"remove:{code}",
        )]
        for code, name in watchlist.items()
    ]
    buttons.append([InlineKeyboardButton("➕ 종목 추가 방법", callback_data="add_help")])
    buttons.append([InlineKeyboardButton("❌ 닫기", callback_data="close")])
    return InlineKeyboardMarkup(buttons)


def build_view_result_keyboard(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("적용", callback_data=f"view_apply:{uid}"),
                InlineKeyboardButton("취소", callback_data=f"view_cancel:{uid}"),
            ]
        ]
    )


# ── help text ─────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "사용 가능한 명령어\n\n"
    "/menu - 관심종목 관리\n"
    "/add 종목코드 - 관심종목 추가\n"
    "/list - 관심종목 목록 확인\n"
    "/view show - 저장된 시장 뷰 보기\n"
    "/view set 시장뷰 - 시장 뷰 저장\n"
    "/view run - 시장 뷰 분석\n"
    "/view clear - 시장 뷰 삭제\n"
    "/help - 도움말"
)


# ── services accessor ─────────────────────────────────────────────────────────

def get_services(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data["services"]


# ── core handlers ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=build_main_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def handle_reply_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    from handlers.view import handle_view_show, run_saved_view
    from handlers.watchlist import cmd_add, cmd_list

    text = (update.message.text or "").strip()

    if text == _BTN_ANALYZE:
        await run_saved_view(update, context)
    elif text == _BTN_VIEW:
        await handle_view_show(update, context)
    elif text == _BTN_LIST:
        await cmd_list(update, context)
    elif text == _BTN_ADD:
        context.user_data["awaiting_stock_code"] = True
        await update.message.reply_text("추가할 종목코드를 입력하세요.\n예: 300750")
    elif context.user_data.get("awaiting_stock_code"):
        context.user_data["awaiting_stock_code"] = False
        context.args = [text]
        await cmd_add(update, context)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.view import handle_view_apply, handle_view_cancel
    from handlers.watchlist import handle_remove_callback

    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("view_apply:"):
        uid = data.split(":", 1)[1]
        await handle_view_apply(query, context, uid)
    elif data.startswith("view_cancel:"):
        uid = data.split(":", 1)[1]
        await handle_view_cancel(query, context, uid)
    elif data == "close":
        await query.message.delete()
    elif data == "add_help":
        await query.message.reply_text("형식: /add 종목코드\n예시: /add 600519")
    elif data.startswith("remove:"):
        code = data.split(":", 1)[1]
        await handle_remove_callback(query, context, code)


# ── app factory ───────────────────────────────────────────────────────────────

def build_telegram_app(services) -> Application:
    app = Application.builder().token(services.settings.bot_token).build()
    app.bot_data["services"] = services
    app.bot_data["stock_news_first_run"] = True
    _register_handlers(app)
    return app


def _register_handlers(app: Application) -> None:
    from handlers.view import cmd_view
    from handlers.watchlist import cmd_add, cmd_list, cmd_menu

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("view", cmd_view))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_button))
