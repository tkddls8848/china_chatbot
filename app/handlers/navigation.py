"""명령어 입력 없이 사용하는 텔레그램 인라인 메뉴."""

from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes


def _keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows]
    )


def main_menu() -> InlineKeyboardMarkup:
    return _keyboard([
        [("📊 국가별 감성", "nav:market"), ("⭐ 관심종목", "nav:watch")],
        [("🔎 리서치", "nav:research"), ("📰 브리핑", "nav:briefing")],
        [("📈 신호 성과", "nav:score"), ("⚙️ 시스템", "nav:system")],
        [("🗂 종목 DB 갱신", "nav:stockdb"), ("❔ 도움말", "nav:help")],
    ])


def persistent_menu() -> ReplyKeyboardMarkup:
    """채팅 입력창 위에 계속 표시되는 메뉴 진입 버튼."""
    return ReplyKeyboardMarkup(
        [
            ["🏠 홈", "📊 감성", "⭐ 관심종목"],
            ["🔎 리서치", "📰 브리핑", "⚙️ 관리"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _back() -> list[list[tuple[str, str]]]:
    return [[("🏠 처음", "nav:home")]]


def _context(context: ContextTypes.DEFAULT_TYPE, args: list[str]):
    return SimpleNamespace(bot_data=context.bot_data, application=context.application, args=args)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    if not data.startswith("nav:"):
        return False

    query = update.callback_query
    message = query.message
    action = data.removeprefix("nav:")
    if action == "home":
        await message.edit_text("<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.", parse_mode="HTML", reply_markup=main_menu())
    elif action == "market":
        await message.edit_text("<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.", parse_mode="HTML", reply_markup=_keyboard([
            [("7일", "nav:market:7"), ("14일", "nav:market:14"), ("30일", "nav:market:30")], *_back()
        ]))
    elif action.startswith("market:"):
        from handlers.commands import cmd_market
        await cmd_market(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "watch":
        await message.edit_text("<b>관심종목</b>", parse_mode="HTML", reply_markup=_keyboard([
            [("목록·삭제", "nav:watch:list"), ("종목 추가", "nav:watch:add")], *_back()
        ]))
    elif action == "watch:list":
        from watchlist import cmd_list
        await cmd_list(update, _context(context, []))
    elif action == "watch:add":
        context.user_data["menu_input"] = "add_stock"
        await message.edit_text("추가할 종목 코드를 숫자로 입력하세요.\n예: 600519", reply_markup=_keyboard(_back()))
    elif action == "research":
        await message.edit_text("<b>리서치</b>", parse_mode="HTML", reply_markup=_keyboard([
            [("주제 보기", "nav:research:show"), ("분석 실행", "nav:research:run")],
            [("주제 설정", "nav:research:set"), ("주제 삭제", "nav:research:clear")], *_back()
        ]))
    elif action.startswith("research:"):
        command = action.split(":", 1)[1]
        if command == "set":
            context.user_data["menu_input"] = "research_topic"
            await message.edit_text("저장할 리서치 주제를 입력하세요.", reply_markup=_keyboard(_back()))
        else:
            from research import cmd_research
            await cmd_research(update, _context(context, [command]))
    elif action == "briefing":
        await message.edit_text("<b>브리핑</b>", parse_mode="HTML", reply_markup=_keyboard([
            [("모닝", "nav:briefing:morning"), ("마감", "nav:briefing:evening")],
            [("주간 성적표", "nav:briefing:scorecard")], *_back()
        ]))
    elif action.startswith("briefing:"):
        from briefing import cmd_briefing
        await cmd_briefing(update, _context(context, [action.split(":", 1)[1]]))
    elif action == "score":
        await message.edit_text("<b>신호 성과</b>", parse_mode="HTML", reply_markup=_keyboard([
            [("현재 신호", "nav:score:live"), ("백테스트", "nav:score:backtest")], *_back()
        ]))
    elif action.startswith("score:"):
        from handlers.commands import cmd_score
        value = action.split(":", 1)[1]
        await cmd_score(update, _context(context, [] if value == "live" else [value]))
    elif action == "system":
        from handlers.commands import cmd_system
        await cmd_system(update, _context(context, []))
    elif action == "stockdb":
        from handlers.commands import cmd_stockdb
        await cmd_stockdb(update, _context(context, ["build"]))
    elif action == "help":
        await message.edit_text("버튼을 눌러 기능을 실행하세요.\n종목 코드와 리서치 주제만 일반 텍스트로 입력합니다.", reply_markup=main_menu())
    return True


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = message.text or ""
    shortcuts = {
        "🏠 홈": "home",
        "📊 감성": "market",
        "⭐ 관심종목": "watch",
        "🔎 리서치": "research",
        "📰 브리핑": "briefing",
        "⚙️ 관리": "system",
    }
    if text == "🏠 홈":
        await message.reply_text("<b>주식 뉴스 봇</b>\n원하는 기능을 선택하세요.", parse_mode="HTML", reply_markup=main_menu())
        return
    if text in shortcuts:
        action = shortcuts[text]
        if action == "market":
            await message.reply_text("<b>국가별 뉴스 감성</b>\n조회 기간을 선택하세요.", parse_mode="HTML", reply_markup=_keyboard([
                [("7일", "nav:market:7"), ("14일", "nav:market:14"), ("30일", "nav:market:30")], *_back()
            ]))
        elif action == "watch":
            await message.reply_text("<b>관심종목</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("목록·삭제", "nav:watch:list"), ("종목 추가", "nav:watch:add")], *_back()
            ]))
        elif action == "research":
            await message.reply_text("<b>리서치</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("주제 보기", "nav:research:show"), ("분석 실행", "nav:research:run")],
                [("주제 설정", "nav:research:set"), ("주제 삭제", "nav:research:clear")], *_back()
            ]))
        elif action == "briefing":
            await message.reply_text("<b>브리핑</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("모닝", "nav:briefing:morning"), ("마감", "nav:briefing:evening")],
                [("주간 성적표", "nav:briefing:scorecard")], *_back()
            ]))
        else:
            await message.reply_text("<b>관리</b>", parse_mode="HTML", reply_markup=_keyboard([
                [("시스템 상태", "nav:system"), ("종목 DB 갱신", "nav:stockdb")], *_back()
            ]))
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
    await message.reply_text("하단 메뉴에서 다음 작업을 선택하세요.", reply_markup=persistent_menu())
