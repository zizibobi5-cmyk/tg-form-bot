"""Утилиты форматирования и разбиения сообщений."""
from __future__ import annotations

from html import escape

from aiogram.types import User as TgUser

import texts

TELEGRAM_MESSAGE_LIMIT = 4096
MAX_MESSAGES_PER_APPLICATION = 3  # "не больше 3х тг лимитов"
MAX_APPLICATION_BODY = TELEGRAM_MESSAGE_LIMIT * MAX_MESSAGES_PER_APPLICATION


def user_link(user: TgUser) -> str:
    """Возвращает HTML-ссылку на пользователя для упоминания в сообщении модераторам/канале."""
    name = escape(user.full_name or "пользователь")
    if user.username:
        return f'<a href="https://t.me/{escape(user.username)}">@{escape(user.username)}</a>'
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def user_link_from_parts(user_id: int, username: str | None, full_name: str | None) -> str:
    name = escape(full_name or "пользователь")
    if username:
        return f'<a href="https://t.me/{escape(username)}">@{escape(username)}</a>'
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def _username_block(username: str | None) -> str:
    if username:
        u = escape(username)
        return f'<a href="https://t.me/{u}">@{u}</a>'
    return "не указан"


def render_application(
    name_surname: str,
    age_height: str,
    magic_abilities: str,
    character: str,
    biography: str,
    interesting_facts: str | None,
    work_position: str,
    place_of_living: str | None,
    roll: str,
    username: str | None,
) -> str:
    """Подставляет поля анкеты в шаблон публикации. Все пользовательские значения экранируются."""
    facts_block = (
        texts.OPTIONAL_FACTS_BLOCK.format(value=escape(interesting_facts))
        if interesting_facts
        else ""
    )
    place_block = (
        texts.OPTIONAL_PLACE_BLOCK.format(value=escape(place_of_living))
        if place_of_living
        else ""
    )
    return texts.APPLICATION_TEMPLATE.format(
        name_surname=escape(name_surname),
        age_height=escape(age_height),
        magic_abilities=escape(magic_abilities),
        character=escape(character),
        biography=escape(biography),
        interesting_facts_block=facts_block,
        work_position=escape(work_position),
        place_of_living_block=place_block,
        roll=escape(roll),
        username=_username_block(username),
    )


def split_text_for_telegram(
    text: str,
    limit: int = TELEGRAM_MESSAGE_LIMIT,
    max_parts: int = MAX_MESSAGES_PER_APPLICATION,
) -> list[str]:
    """Делит длинный HTML-текст на куски, чтобы каждый влезал в лимит Telegram.
    Старается резать по двойным переводам строк, потом по одиночным, потом «жёстко».

    ВНИМАНИЕ: чтобы не порвать HTML-теги, используем только теги, которые наш шаблон
    кладёт на одной строке (b, code, a) — мы режем по \\n, что безопасно для нашего
    шаблона. Если кусок всё ещё слишком длинный (очень длинная биография без переносов),
    режем по символам.
    """
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        # ищем последний \n\n перед лимитом
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
        if len(parts) >= max_parts - 1:
            # последнее «ведро» — обрезаем остаток жёстко
            tail = remaining
            if len(tail) > limit:
                tail = tail[: limit - 1] + "…"
            parts.append(tail)
            break
    return parts
