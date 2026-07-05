"""텔레그램 명령어 접근 제어.

ALLOWED_CHAT_IDS가 비어 있으면 기존처럼 모두 허용한다. 채워져 있으면 해당
chat_id에서 온 업데이트만 처리하고, 나머지는 조용히 무시한다(봇 존재를
드러내지 않기 위해 응답하지 않는다).
"""

import functools
import logging
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from core.config import ALLOWED_CHAT_IDS

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def is_allowed_update(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    chat = update.effective_chat
    return chat is not None and chat.id in ALLOWED_CHAT_IDS


def restricted(handler: Handler) -> Handler:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed_update(update):
            chat = update.effective_chat
            logger.warning(
                "[ACCESS] 허용되지 않은 채팅의 요청 무시: chat_id=%s",
                chat.id if chat else "unknown",
            )
            return
        await handler(update, context)

    return wrapper
