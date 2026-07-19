"""명령어 입력 없이 사용하는 텔레그램 인라인 메뉴."""

from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes


def _keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows]
    )


_NAV_FEATURES = {
    "market": "market_sentiment",
    "watch": "watchlist",
    "research": "research",
    "briefing": "briefing",
    "score": "signal_scoring",
    "system": "system_admin",
    "stockdb": "instruments",
    "help": "system_admin",
}


def _enabled_keys(context: ContextTypes.DEFAULT_TYPE) -> frozenset[str] | None:
    registry = context.bot_data.get("feature_registry")
    return registry.enabled_keys if registry is not None else None


def _filter_nav_rows(
    rows: list[list[tuple[str, str]]],
    enabled_features: frozenset[str] | set[str] | None,
) -> list[list[tuple[str, str]]]:
    if enabled_features is None:
        return rows
    filtered = []
    for row in rows:
        kept = [
            item
            for item in row
            if _NAV_FEATURES.get(item[1].removeprefix("nav:").split(":", 1)[0])
            in enabled_features
        ]
        if kept:
            filtered.append(kept)
    return filtered


def main_menu(
    feature_source=None,
) -> InlineKeyboardMarkup:
    if feature_source is not None and hasattr(feature_source, "menu_specs"):
        grouped: dict[int, list[tuple[str, str]]] = {}
        for item in feature_source.menu_specs():
            grouped.setdefault(item.row, []).append(
                (item.label, item.callback_data)
            )
        return _keyboard([grouped[row] for row in sorted(grouped)])
    if feature_source is not None and hasattr(feature_source, "enabled_keys"):
        feature_source = feature_source.enabled_keys

    rows = [
        [("📊 국가별 감성", "nav:market"), ("⭐ 관심종목", "nav:watch")],
        [("🔎 리서치", "nav:research"), ("📰 브리핑", "nav:briefing")],
        [("📈 신호 성과", "nav:score"), ("⚙️ 시스템", "nav:system")],
        [("🗂 종목 DB 갱신", "nav:stockdb"), ("❔ 도움말", "nav:help")],
    ]
    return _keyboard(_filter_nav_rows(rows, feature_source))


def persistent_menu(
    feature_source=None,
) -> ReplyKeyboardMarkup:
    """채팅 입력창 위에 계속 표시되는 메뉴 진입 버튼."""
    if feature_source is not None and hasattr(feature_source, "menu_specs"):
        grouped: dict[int, list[str]] = {0: ["🏠 홈"]}
        for item in feature_source.menu_specs():
            if item.persistent_label:
                grouped.setdefault(item.persistent_row, []).append(
                    item.persistent_label
                )
        rows = [grouped[row] for row in sorted(grouped)]
        return ReplyKeyboardMarkup(
            rows,
            resize_keyboard=True,
            is_persistent=True,
        )
    if feature_source is not None and hasattr(feature_source, "enabled_keys"):
        feature_source = feature_source.enabled_keys

    feature_by_label = {
        "📊 감성": "market_sentiment",
        "⭐ 관심종목": "watchlist",
        "🔎 리서치": "research",
        "📰 브리핑": "briefing",
        "📈 성과": "signal_scoring",
        "⚙️ 관리": "system_admin",
    }
    rows = [
        ["🏠 홈", "📊 감성", "⭐ 관심종목"],
        ["🔎 리서치", "📰 브리핑", "📈 성과"],
        ["⚙️ 관리"],
    ]
    if feature_source is not None:
        rows = [
            [
                label
                for label in row
                if label == "🏠 홈"
                or feature_by_label.get(label) in feature_source
            ]
            for row in rows
        ]
        rows = [row for row in rows if row]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


async def refresh_persistent_menu(
    message,
    feature_source=None,
) -> None:
    await message.reply_text(
        "⌨️ 하단 메뉴를 최신 상태로 갱신했습니다.",
        reply_markup=persistent_menu(feature_source),
    )


def _back() -> list[list[tuple[str, str]]]:
    return [[("🏠 처음", "nav:home")]]


def market_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("7일", "nav:market:7"), ("14일", "nav:market:14"), ("30일", "nav:market:30")],
        *_back(),
    ])


def research_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("주제 보기", "nav:research:show"), ("분석 실행", "nav:research:run")],
        [("주제 설정", "nav:research:set"), ("주제 삭제", "nav:research:clear")],
        *_back(),
    ])


def briefing_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("모닝", "nav:briefing:morning"), ("마감", "nav:briefing:evening")],
        [("주간 성적표", "nav:briefing:scorecard")],
        *_back(),
    ])


def score_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("운영 신호", "nav:score:live")],
        *_back(),
    ])


def _context(context: ContextTypes.DEFAULT_TYPE, args: list[str]):
    return SimpleNamespace(bot_data=context.bot_data, application=context.application, args=args)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    if not data.startswith("nav:"):
        return False

    query = update.callback_query
    message = query.message
    action = data.removeprefix("nav:")
    feature_registry = context.bot_data.get("feature_registry")
    enabled = _enabled_keys(context)
    menu_source = feature_registry or enabled
    root_action = action.split(":", 1)[0]
    required_feature = _NAV_FEATURES.get(root_action)
    if (
        enabled is not None
        and required_feature is not None
        and required_feature not in enabled
    ):
        await message.edit_text(
            "이 기능은 현재 비활성화되어 있습니다.",
            reply_markup=main_menu(menu_source),
        )
        return True
    if action == "home":
        await refresh_persistent_menu(message, menu_source)
        await message.edit_text("<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.", parse_mode="HTML", reply_markup=main_menu(menu_source))
    elif action == "market":
        await message.edit_text(
            "<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.",
            parse_mode="HTML",
            reply_markup=market_menu(),
        )
    elif action.startswith("market:"):
        from handlers.commands import cmd_market
        await cmd_market(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "watch":
        from watchlist import cmd_menu
        await cmd_menu(update, _context(context, []))
    elif action == "watch:list":
        from watchlist import cmd_menu
        await cmd_menu(update, _context(context, []))
    elif action == "watch:add":
        from watchlist.keyboards import build_add_market_keyboard
        context.user_data.pop("menu_input", None)
        context.user_data.pop("add_market", None)
        await message.edit_text(
            "<b>종목추가</b>\n추가할 국가와 시장을 선택하세요.",
            parse_mode="HTML",
            reply_markup=build_add_market_keyboard(),
        )
    elif action == "research":
        await message.edit_text(
            "<b>리서치</b>",
            parse_mode="HTML",
            reply_markup=research_menu(),
        )
    elif action.startswith("research:"):
        command = action.split(":", 1)[1]
        if command == "set":
            context.user_data["menu_input"] = "research_topic"
            await message.edit_text("저장할 리서치 주제를 입력하세요.", reply_markup=_keyboard(_back()))
        else:
            from research import cmd_research
            await cmd_research(update, _context(context, [command]))
    elif action == "briefing":
        await message.edit_text(
            "<b>브리핑</b>",
            parse_mode="HTML",
            reply_markup=briefing_menu(),
        )
    elif action.startswith("briefing:"):
        from briefing import cmd_briefing
        await cmd_briefing(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "score":
        await message.edit_text(
            "<b>신호 성과</b>",
            parse_mode="HTML",
            reply_markup=score_menu(),
        )
    elif action.startswith("score:"):
        from handlers.commands import cmd_score
        await cmd_score(update, _context(context, []))
    elif action == "system":
        from handlers.commands import cmd_system
        await cmd_system(update, _context(context, []))
    elif action == "stockdb":
        from handlers.commands import cmd_stockdb
        await cmd_stockdb(update, _context(context, ["build"]))
    elif action == "help":
        await message.edit_text("버튼을 눌러 기능을 실행하세요.\n종목 코드와 리서치 주제만 일반 텍스트로 입력합니다.", reply_markup=main_menu(menu_source))
    return True


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = message.text or ""
    feature_registry = context.bot_data.get("feature_registry")
    enabled = _enabled_keys(context)
    menu_source = feature_registry or enabled
    shortcuts = {
        "🏠 홈": "home",
        "📊 감성": "market",
        "⭐ 관심종목": "watch",
        "🔎 리서치": "research",
        "📰 브리핑": "briefing",
        "📈 성과": "score",
        "⚙️ 관리": "system",
    }
    if text == "🏠 홈":
        await refresh_persistent_menu(message, menu_source)
        await message.reply_text("<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.", parse_mode="HTML", reply_markup=main_menu(menu_source))
        return
    if text in shortcuts:
        action = shortcuts[text]
        required_feature = _NAV_FEATURES.get(action)
        if (
            enabled is not None
            and required_feature is not None
            and required_feature not in enabled
        ):
            await message.reply_text("이 기능은 현재 비활성화되어 있습니다.")
            return
        if action == "market":
            await message.reply_text(
                "<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.",
                parse_mode="HTML",
                reply_markup=market_menu(),
            )
        elif action == "watch":
            from watchlist import cmd_menu
            await cmd_menu(update, _context(context, []))
        elif action == "research":
            await message.reply_text(
                "<b>리서치</b>",
                parse_mode="HTML",
                reply_markup=research_menu(),
            )
        elif action == "briefing":
            await message.reply_text(
                "<b>브리핑</b>",
                parse_mode="HTML",
                reply_markup=briefing_menu(),
            )
        elif action == "score":
            await message.reply_text(
                "<b>신호 성과</b>",
                parse_mode="HTML",
                reply_markup=score_menu(),
            )
        else:
            await message.reply_text("<b>관리</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("시스템 상태", "nav:system"), ("종목 DB 갱신", "nav:stockdb")], *_back()
            ]))
        return

    if context.user_data.get("add_market"):
        from watchlist import cmd_add
        await cmd_add(update, _context(context, [text.strip()]))
        return

    action = context.user_data.pop("menu_input", None)
    if action is None:
        return
    if action == "add_stock":
        from watchlist import cmd_add
        await cmd_add(update, _context(context, [text.strip()]))
    elif action == "research_topic":
        from research import cmd_research
        await cmd_research(update, _context(context, ["set", text.strip()]))
    await message.reply_text("하단 메뉴에서 다음 작업을 선택하세요.", reply_markup=persistent_menu(menu_source))
