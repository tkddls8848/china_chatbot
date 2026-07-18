import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from core import access
from handlers.menu_status import set_menu_button_text
from handlers.navigation import (
    handle_menu_callback,
    handle_menu_text,
    persistent_menu,
    research_menu,
    score_menu,
)
from handlers.commands import configure_telegram_menu
from watchlist.handlers import cmd_menu, handle_watchlist_callback
from watchlist.keyboards import build_list_keyboard


def _update(chat_id):
    chat = SimpleNamespace(id=chat_id) if chat_id is not None else None
    return SimpleNamespace(effective_chat=chat)


def test_empty_allowlist_allows_everyone(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset())
    assert access.is_allowed_update(_update(12345)) is True


def test_allowlist_blocks_other_chats(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({111}))
    assert access.is_allowed_update(_update(111)) is True
    assert access.is_allowed_update(_update(222)) is False
    assert access.is_allowed_update(_update(None)) is False


def test_restricted_decorator_skips_disallowed(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({111}))
    calls = []

    @access.restricted
    async def handler(update, context):
        calls.append(update.effective_chat.id)

    asyncio.run(handler(_update(111), None))
    asyncio.run(handler(_update(222), None))
    assert calls == [111]


def test_restricted_decorator_updates_request_status(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset())
    edits = []

    class StatusMessage:
        async def edit_text(self, text):
            edits.append(text)

    class RequestMessage:
        async def reply_text(self, text):
            assert text == "⏳ 요청 작업 처리 중..."
            return StatusMessage()

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=123),
        effective_message=RequestMessage(),
    )

    @access.restricted
    async def handler(update, context):
        return None

    asyncio.run(handler(update, None))
    assert edits == ["✅ 요청 작업 처리 완료"]


def test_menu_jobs_suppress_chat_status(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset())
    replies = []

    class RequestMessage:
        async def reply_text(self, text):
            replies.append(text)

    @access.restricted
    async def handler(update, context):
        return None

    for callback_data in (
        "nav:research:run",
        "nav:market:7",
        "nav:briefing:morning",
    ):
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=123),
            effective_message=RequestMessage(),
            callback_query=SimpleNamespace(data=callback_data),
        )
        asyncio.run(handler(update, SimpleNamespace(bot_data={})))
    assert replies == []


def test_menu_status_changes_only_target_button():
    class Message:
        def __init__(self):
            self.reply_markup = research_menu()

        async def edit_reply_markup(self, reply_markup):
            self.reply_markup = reply_markup

    message = Message()
    asyncio.run(
        set_menu_button_text(
            message,
            "nav:research:run",
            "◑ AI 분석 중",
        )
    )

    buttons = {
        button.callback_data: button.text
        for row in message.reply_markup.inline_keyboard
        for button in row
    }
    assert buttons["nav:research:run"] == "◑ AI 분석 중"
    assert buttons["nav:research:show"] == "주제 보기"


def test_persistent_menu_exposes_score_button():
    labels = {
        button.text
        for row in persistent_menu().keyboard
        for button in row
    }
    assert "📈 성과" in labels


def test_score_menu_exposes_live_and_backtest_actions():
    buttons = {
        button.callback_data: button.text
        for row in score_menu().inline_keyboard
        for button in row
    }
    assert buttons["nav:score:live"] == "운영 신호"
    assert buttons["nav:score:backtest"] == "백테스트"


def test_home_text_refreshes_persistent_menu_before_inline_home():
    class Message:
        text = "🏠 홈"

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append((text, kwargs["reply_markup"]))

    message = Message()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(user_data={}, bot_data={}, application=None)

    asyncio.run(handle_menu_text(update, context))

    assert len(message.replies) == 2
    assert "하단 메뉴" in message.replies[0][0]
    labels = {
        button.text
        for row in message.replies[0][1].keyboard
        for button in row
    }
    assert "📈 성과" in labels
    assert message.replies[1][1].inline_keyboard


def test_bot_startup_pushes_latest_persistent_menu(monkeypatch):
    sent = []

    class Bot:
        async def set_my_commands(self, commands):
            self.commands = commands

        async def set_chat_menu_button(self, menu_button):
            self.menu_button = menu_button

        async def send_message(self, **kwargs):
            sent.append(kwargs)

    app = SimpleNamespace(bot=Bot())
    monkeypatch.setattr("handlers.commands.TELEGRAM_CHAT_ID", "chat")

    asyncio.run(configure_telegram_menu(app))

    assert sent[0]["chat_id"] == "chat"
    labels = {
        button.text
        for row in sent[0]["reply_markup"].keyboard
        for button in row
    }
    assert "📈 성과" in labels


def test_menu_command_opens_delete_list_directly():
    class Watchlist:
        async def get_all(self):
            return {"600519": "귀주모태주"}

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.reply_markup = kwargs["reply_markup"]

    message = Message()
    update = SimpleNamespace(effective_message=message, callback_query=None)
    context = SimpleNamespace(bot_data={"watchlist_manager": Watchlist()})
    asyncio.run(cmd_menu(update, context))

    buttons = {
        button.callback_data: button.text
        for row in message.reply_markup.inline_keyboard
        for button in row
    }
    assert message.text.startswith("<b>관심종목 관리</b>")
    assert buttons["remove:600519"] == "삭제: 귀주모태주 (600519)"
    assert buttons["add_stock"] == "종목추가"


def test_navigation_watch_opens_delete_list_directly():
    class Watchlist:
        async def get_all(self):
            return {"600519": "귀주모태주"}

    class Message:
        async def edit_text(self, text, **kwargs):
            self.text = text
            self.reply_markup = kwargs["reply_markup"]

    message = Message()
    update = SimpleNamespace(
        effective_message=message,
        callback_query=SimpleNamespace(message=message),
    )
    context = SimpleNamespace(
        user_data={},
        bot_data={"watchlist_manager": Watchlist()},
        application=None,
    )
    handled = asyncio.run(
        handle_menu_callback(update, context, "nav:watch")
    )
    buttons = {
        button.callback_data: button.text
        for row in message.reply_markup.inline_keyboard
        for button in row
    }
    assert handled is True
    assert message.text.startswith("<b>관심종목 관리</b>")
    assert buttons["remove:600519"] == "삭제: 귀주모태주 (600519)"
    assert buttons["add_stock"] == "종목추가"


def test_watchlist_add_button_opens_market_selector_directly():
    keyboard = build_list_keyboard({"600519": "귀주모태주"})
    add_button = next(
        button
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data == "add_stock"
    )
    assert add_button.text == "종목추가"

    class Message:
        async def edit_text(self, text, **kwargs):
            self.text = text
            self.reply_markup = kwargs["reply_markup"]

    message = Message()
    context = SimpleNamespace(
        user_data={"menu_input": "add_stock", "add_market": "CN:SH"},
    )
    handled = asyncio.run(
        handle_watchlist_callback(
            SimpleNamespace(message=message),
            context,
            "add_stock",
        )
    )
    callbacks = {
        button.callback_data
        for row in message.reply_markup.inline_keyboard
        for button in row
    }
    assert handled is True
    assert message.text.startswith("<b>종목추가</b>")
    assert "add_market:CN:SH" in callbacks
    assert context.user_data == {}
