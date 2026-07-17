from typing import Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_list_keyboard(watchlist: Dict[str, str]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"삭제: {name} ({code})",
                callback_data=f"remove:{code}",
            )
        ]
        for code, name in watchlist.items()
    ]
    buttons.append([InlineKeyboardButton("종목 추가 방법", callback_data="add_help")])
    buttons.append([InlineKeyboardButton("닫기", callback_data="close")])
    buttons.append([
        InlineKeyboardButton("⬅️ 관심종목", callback_data="nav:watch"),
        InlineKeyboardButton("🏠 처음", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(buttons)
