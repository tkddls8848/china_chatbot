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
