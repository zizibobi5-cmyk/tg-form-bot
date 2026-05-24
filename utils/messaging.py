"""Утилиты отправки длинных анкет (медиагруппа + 1–3 текстовых сообщения)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto

from utils.formatting import split_text_for_telegram

logger = logging.getLogger(__name__)

# Человекочитаемые лейблы полей анкеты — для подписи копируемых сообщений
# при публикации в канал с премиум-эмодзи.
FIELD_LABELS: dict[str, str] = {
    "name_surname": "<b>Имя/Фамилия:</b>",
    "age_height": "<b>Возраст/Рост:</b>",
    "magic_abilities": "<b>Магические способности:</b>",
    "character": "<b>Характер:</b>",
    "biography": "<b>Биография:</b>",
    "interesting_facts": "<b>Интересные факты:</b>",
    "work_position": "<b>Место работы / должность / факультет / орден / фракции:</b>",
    "place_of_living": "<b>Место проживания:</b>",
    "roll": "<b>Ролл:</b>",
}


async def copy_emoji_fields(
    bot: Bot,
    chat_id: int,
    user_chat_id: int,
    field_message_ids: dict[str, int],
    field_html_map: dict[str, str | None],
    *,
    header: str | None = None,
) -> list[int]:
    """Для полей, в чьём html есть `<tg-emoji ...>`, шлёт лейбл + copy_message оригинала.

    Нужно, потому что Telegram режет custom_emoji из сообщений, которые бот шлёт
    в канал, а `copy_message` сохраняет все entities исходного сообщения.
    Если у поля нет message_id или пользователь удалил исходник — пропускаем молча.
    """
    fields_with_emoji: list[str] = [
        name for name, html in field_html_map.items()
        if html and "<tg-emoji " in html and field_message_ids.get(name)
    ]
    if not fields_with_emoji:
        return []

    sent_ids: list[int] = []
    if header:
        try:
            msg = await bot.send_message(chat_id=chat_id, text=header)
            sent_ids.append(msg.message_id)
        except TelegramAPIError as e:
            logger.warning("Failed to send emoji-copies header: %s", e)

    for field_name in fields_with_emoji:
        label = FIELD_LABELS.get(field_name, f"<b>{field_name}:</b>")
        msg_id = int(field_message_ids[field_name])
        try:
            lbl_msg = await bot.send_message(chat_id=chat_id, text=label)
            sent_ids.append(lbl_msg.message_id)
            copied = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=user_chat_id,
                message_id=msg_id,
            )
            sent_ids.append(copied.message_id)
        except TelegramAPIError as e:
            logger.warning(
                "copy_message failed for field %s (user_chat=%s msg=%s): %s",
                field_name, user_chat_id, msg_id, e,
            )
    return sent_ids


async def _send_photos(bot: Bot, chat_id: int, photo_file_ids: list[str]) -> list[int]:
    if not photo_file_ids:
        return []
    if len(photo_file_ids) >= 2:
        media = [InputMediaPhoto(media=fid) for fid in photo_file_ids]
        sent = await bot.send_media_group(chat_id=chat_id, media=media)
        return [m.message_id for m in sent]
    msg = await bot.send_photo(chat_id=chat_id, photo=photo_file_ids[0])
    return [msg.message_id]


async def _send_text_parts(
    bot: Bot,
    chat_id: int,
    body_html: str,
    final_reply_markup: InlineKeyboardMarkup | None,
    delay_between: float,
) -> tuple[list[int], int | None]:
    parts = split_text_for_telegram(body_html)
    ids: list[int] = []
    last_id: int | None = None
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        markup = final_reply_markup if is_last else None
        msg = await bot.send_message(chat_id=chat_id, text=part, reply_markup=markup)
        ids.append(msg.message_id)
        last_id = msg.message_id
        if not is_last and delay_between > 0:
            await asyncio.sleep(delay_between)
    return ids, last_id


async def send_application_messages(
    bot: Bot,
    chat_id: int,
    body_html: str,
    photo_file_ids: list[str],
    final_reply_markup: InlineKeyboardMarkup | None = None,
    *,
    text_first: bool = False,
    delay_between_texts: float = 0.0,
    delay_before_photos: float = 0.0,
) -> tuple[list[int], int | None]:
    """Отправляет анкету: фото + текст (1–3 сообщения), либо в обратном порядке с задержками.

    Возвращает (id_всех_сообщений, id_последнего_текстового_сообщения).

    Параметры:
    - text_first: если True, сначала отправляются тексты, потом фото (с задержкой `delay_before_photos`).
      Если False — фото идут первыми (как раньше).
    - delay_between_texts: пауза в секундах между текстовыми сообщениями (если их несколько).
    - delay_before_photos: пауза перед отправкой фото (имеет смысл только при text_first=True).
    """
    sent_ids: list[int] = []
    last_text_id: int | None = None

    if text_first:
        text_ids, last_text_id = await _send_text_parts(
            bot, chat_id, body_html, final_reply_markup, delay_between_texts
        )
        sent_ids.extend(text_ids)
        if photo_file_ids and delay_before_photos > 0:
            await asyncio.sleep(delay_before_photos)
        sent_ids.extend(await _send_photos(bot, chat_id, photo_file_ids))
    else:
        sent_ids.extend(await _send_photos(bot, chat_id, photo_file_ids))
        text_ids, last_text_id = await _send_text_parts(
            bot, chat_id, body_html, final_reply_markup, delay_between_texts
        )
        sent_ids.extend(text_ids)

    return sent_ids, last_text_id
