"""명령어 입력 없이 사용하는 텔레그램 인라인 메뉴."""

from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes


def _keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows]
    )


def main_menu(registry) -> InlineKeyboardMarkup:
    grouped: dict[int, list[tuple[str, str]]] = {}
    for item in registry.menu_specs():
        grouped.setdefault(item.row, []).append((item.label, item.callback_data))
    return _keyboard([grouped[row] for row in sorted(grouped)])


def persistent_menu(registry) -> ReplyKeyboardMarkup:
    """채팅 입력창 위에 계속 표시되는 메뉴 진입 버튼."""
    grouped: dict[int, list[str]] = {0: ["🏠 홈"]}
    for item in registry.menu_specs():
        if item.persistent_label:
            grouped.setdefault(item.persistent_row, []).append(
                item.persistent_label
            )
    return ReplyKeyboardMarkup(
        [grouped[row] for row in sorted(grouped)],
        resize_keyboard=True,
        is_persistent=True,
    )


async def refresh_persistent_menu(
    message,
    registry,
) -> None:
    await message.reply_text(
        "⌨️ 하단 메뉴를 최신 상태로 갱신했습니다.",
        reply_markup=persistent_menu(registry),
    )


def _back() -> list[list[tuple[str, str]]]:
    return [[("🏠 처음", "nav:home")]]


def market_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("7일", "nav:market:7"), ("14일", "nav:market:14"), ("30일", "nav:market:30")],
        *_back(),
    ])


def anomaly_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("7일", "nav:anomaly:7"), ("14일", "nav:anomaly:14"), ("30일", "nav:anomaly:30")],
        *_back(),
    ])


def research_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("주제 보기", "nav:research:show"), ("분석 실행", "nav:research:run")],
        [("주제 설정", "nav:research:set"), ("주제 삭제", "nav:research:clear")],
        *_back(),
    ])


def system_menu() -> InlineKeyboardMarkup:
    """시스템 상태 아래에 붙는 하위 항목. `/system`의 인자를 버튼으로 옮긴 것이다."""
    return _keyboard([
        [("📋 기능 카탈로그", "nav:system:features"), ("🧮 뉴스 사전선별", "nav:system:prefilter")],
        *_back(),
    ])


def _context(context: ContextTypes.DEFAULT_TYPE, args: list[str]):
    # user_data를 그대로 전달해야 프록시로 호출되는 핸들러(cmd_add 등)가
    # add_market 같은 대화 상태에 접근할 수 있다(SimpleNamespace에는 기본으로 없음).
    return SimpleNamespace(
        bot_data=context.bot_data,
        user_data=context.user_data,
        application=context.application,
        args=args,
    )


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    if not data.startswith("nav:"):
        return False

    query = update.callback_query
    message = query.message
    action = data.removeprefix("nav:")
    registry = context.bot_data["feature_registry"]
    required_feature = registry.menu_owner(data)
    if required_feature is not None and not registry.is_enabled(required_feature):
        await message.edit_text(
            "이 기능은 현재 비활성화되어 있습니다.",
            reply_markup=main_menu(registry),
        )
        return True
    if action == "home":
        await refresh_persistent_menu(message, registry)
        await message.edit_text(
            "<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.",
            parse_mode="HTML",
            reply_markup=main_menu(registry),
        )
    elif action == "market":
        await message.edit_text(
            "<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.",
            parse_mode="HTML",
            reply_markup=market_menu(),
        )
    elif action.startswith("market:"):
        from features.market_sentiment.handlers import cmd_market
        await cmd_market(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "anomaly":
        await message.edit_text(
            "<b>시장 서술 이상(파일럿)</b>\n조회 기간을 선택하세요.",
            parse_mode="HTML",
            reply_markup=anomaly_menu(),
        )
    elif action.startswith("anomaly:"):
        from features.market_sentiment.handlers import cmd_anomaly
        await cmd_anomaly(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "polymarket":
        from features.market_sentiment.handlers import cmd_polymarket
        await cmd_polymarket(update, _context(context, []))
    elif action in {"watch", "watch:list"}:
        from watchlist.handlers import cmd_menu
        await cmd_menu(update, _context(context, []))
    elif action == "watch:add":
        from watchlist.handlers import handle_watchlist_callback
        await handle_watchlist_callback(query, context, "add_stock")
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
            from research.handlers import cmd_research
            await cmd_research(update, _context(context, [command]))
    elif action == "briefing":
        from briefing.service import cmd_briefing
        await cmd_briefing(update, _context(context, []))
    elif action.startswith("briefing:"):
        from briefing.service import cmd_briefing
        await cmd_briefing(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "system":
        from features.system_admin.handlers import cmd_system
        await cmd_system(update, _context(context, []))
    elif action.startswith("system:"):
        from features.system_admin.handlers import cmd_system
        await cmd_system(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "stockdb":
        from features.instruments.handlers import cmd_stockdb
        await cmd_stockdb(update, _context(context, ["build"]))
    elif action == "help":
        await message.edit_text(
            "버튼을 눌러 기능을 실행하세요.\n"
            "종목 코드와 리서치 주제만 일반 텍스트로 입력합니다.",
            reply_markup=main_menu(registry),
        )
    return True


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = message.text or ""
    registry = context.bot_data["feature_registry"]
    if text == "🏠 홈":
        await refresh_persistent_menu(message, registry)
        await message.reply_text(
            "<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.",
            parse_mode="HTML",
            reply_markup=main_menu(registry),
        )
        return
    callback_data = registry.persistent_callback(text)
    if callback_data is not None:
        required_feature = registry.menu_owner(callback_data)
        if required_feature is not None and not registry.is_enabled(required_feature):
            await message.reply_text("이 기능은 현재 비활성화되어 있습니다.")
            return
        action = callback_data.removeprefix("nav:")
        if action == "market":
            await message.reply_text(
                "<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.",
                parse_mode="HTML",
                reply_markup=market_menu(),
            )
        elif action == "watch":
            from watchlist.handlers import cmd_menu
            await cmd_menu(update, _context(context, []))
        elif action == "research":
            await message.reply_text(
                "<b>리서치</b>",
                parse_mode="HTML",
                reply_markup=research_menu(),
            )
        elif action == "briefing":
            from briefing.service import cmd_briefing
            await cmd_briefing(update, _context(context, []))
        elif action == "anomaly":
            await message.reply_text(
                "<b>시장 서술 이상(파일럿)</b>\n조회 기간을 선택하세요.",
                parse_mode="HTML",
                reply_markup=anomaly_menu(),
            )
        elif action == "polymarket":
            from features.market_sentiment.handlers import cmd_polymarket
            await cmd_polymarket(update, _context(context, []))
        elif action == "system":
            await message.reply_text("<b>관리</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("시스템 상태", "nav:system"), ("종목 DB 갱신", "nav:stockdb")], *_back()
            ]))
        else:
            # 알 수 없는 persistent 버튼 — 새 메뉴를 추가할 때 이 분기를 잊으면
            # 예전에는 조용히 "⚙️ 관리" 화면으로 잘못 떨어졌다. 그 대신 홈으로
            # 보내 틀린 화면이 아니라 눈에 띄는 결과가 나오게 한다.
            await message.reply_text(
                "<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.",
                parse_mode="HTML",
                reply_markup=main_menu(registry),
            )
        return

    if context.user_data.get("add_market"):
        from watchlist.handlers import cmd_add
        await cmd_add(update, _context(context, [text.strip()]))
        return

    action = context.user_data.pop("menu_input", None)
    if action is None:
        return
    if action == "research_topic":
        from research.handlers import cmd_research
        await cmd_research(update, _context(context, ["set", text.strip()]))
    await message.reply_text(
        "하단 메뉴에서 다음 작업을 선택하세요.",
        reply_markup=persistent_menu(registry),
    )
