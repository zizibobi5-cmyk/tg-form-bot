"""Клавиатуры для обычного пользователя."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import texts


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_SEND_APPLICATION)],
            [KeyboardButton(text=texts.BTN_ASK_QUESTION), KeyboardButton(text=texts.BTN_RULES)],
        ],
        resize_keyboard=True,
    )


def photos_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_PHOTOS_DONE)],
            [KeyboardButton(text=texts.BTN_PHOTOS_CLEAR), KeyboardButton(text=texts.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def skip_cancel_kb() -> ReplyKeyboardMarkup:
    """Клавиатура для опциональных шагов: «Пропустить» + «Отмена»."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_SKIP)],
            [KeyboardButton(text=texts.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_PREVIEW_SEND, callback_data="preview:send")],
            [InlineKeyboardButton(text=texts.BTN_PREVIEW_EDIT, callback_data="preview:edit")],
            [InlineKeyboardButton(text=texts.BTN_PREVIEW_CANCEL, callback_data="preview:cancel")],
        ]
    )


def resend_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=texts.BTN_RESEND_YES, callback_data="resend:yes"),
                InlineKeyboardButton(text=texts.BTN_RESEND_NO, callback_data="resend:no"),
            ]
        ]
    )
