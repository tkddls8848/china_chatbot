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

_HANDLER_LABELS = {
    "cmd_start": "메뉴 열기",
    "cmd_help": "도움말 조회",
    "cmd_menu": "관심종목 메뉴 조회",
    "cmd_add": "관심종목 추가",
    "cmd_list": "관심종목 목록 조회",
    "cmd_view": "종목 감성 조회",
    "cmd_market": "국가별 뉴스 감성 차트 생성",
    "cmd_score": "신호 성과 채점",
    "cmd_research": "리서치 분석",
    "cmd_briefing": "브리핑 생성",
    "cmd_stockdb": "종목 DB 갱신",
    "cmd_system": "시스템 상태 조회",
}

_MENU_LABELS = {
    "market": "국가별 뉴스 감성 차트 생성",
    "watch": "관심종목 관리",
    "research": "리서치 분석",
    "briefing": "브리핑 생성",
    "score": "신호 성과 채점",
    "system": "시스템 상태 조회",
    "stockdb": "종목 DB 갱신",
    "home": "메인 메뉴 열기",
    "help": "도움말 조회",
}


def request_label(update: Update, handler_name: str) -> str:
    query = getattr(update, "callback_query", None)
    data = str(getattr(query, "data", ""))
    if data.startswith("nav:"):
        return _MENU_LABELS.get(data.removeprefix("nav:").split(":", 1)[0], "메뉴 작업")
    if data.startswith("remove:"):
        return "관심종목 삭제"
    if data.startswith("research:"):
        return "리서치 결과 반영"
    return _HANDLER_LABELS.get(handler_name, "요청 작업")


def is_allowed_update(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    chat = update.effective_chat
    return chat is not None and chat.id in ALLOWED_CHAT_IDS


def restricted(handler: Handler, show_status: bool = True) -> Handler:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed_update(update):
            chat = update.effective_chat
            logger.warning(
                "[ACCESS] 허용되지 않은 채팅의 요청 무시: chat_id=%s",
                chat.id if chat else "unknown",
            )
            return
        message = getattr(update, "effective_message", None)
        status = None
        label = request_label(update, handler.__name__)
        bot_data = getattr(context, "bot_data", {})
        background_tasks_before = len(bot_data.get("research_tasks", set()))
        query = getattr(update, "callback_query", None)
        callback_data = str(getattr(query, "data", ""))
        suppress_menu_status = (
            handler.__name__ == "cmd_research"
            or callback_data == "nav:research:run"
            or callback_data.startswith("nav:market:")
            or callback_data.startswith("nav:briefing:")
        )
        if show_status and not suppress_menu_status and message is not None:
            try:
                status = await message.reply_text(f"⏳ {label} 처리 중...")
            except Exception:
                logger.warning("[STATUS] 처리 상태 메시지 전송 실패", exc_info=True)

        try:
            await handler(update, context)
        except Exception:
            if status is not None:
                try:
                    await status.edit_text(f"❌ {label} 처리 실패. 잠시 후 다시 시도해 주세요.")
                except Exception:
                    logger.warning("[STATUS] 실패 상태 메시지 갱신 실패", exc_info=True)
            raise
        else:
            if status is not None:
                try:
                    background_tasks_after = len(bot_data.get("research_tasks", set()))
                    if background_tasks_after > background_tasks_before:
                        await status.edit_text(f"⏳ {label} 백그라운드 실행 중...")
                    else:
                        await status.edit_text(f"✅ {label} 처리 완료")
                except Exception:
                    logger.warning("[STATUS] 완료 상태 메시지 갱신 실패", exc_info=True)

    return wrapper
