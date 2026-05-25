"""Клавиатуры для модераторов."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import texts


def moderation_kb(app_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=texts.MOD_ACCEPT, callback_data=f"mod:accept:{app_id}"),
                InlineKeyboardButton(text=texts.MOD_REJECT, callback_data=f"mod:reject:{app_id}"),
            ],
            [InlineKeyboardButton(text=texts.MOD_BAN, callback_data=f"mod:ban:{app_id}")],
        ]
    )


def question_kb(q_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.MOD_ANSWER_BTN, callback_data=f"q:answer:{q_id}")],
            [InlineKeyboardButton(text=texts.MOD_BAN, callback_data=f"q:ban:{q_id}")],
        ]
    )
