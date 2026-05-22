"""Админ-команды (доступны только пользователям из ADMIN_IDS).
Работают в личке с ботом и в чате модераторов (там также можно использовать Reply)."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import get_settings
from db.queries import (
    add_moderator,
    ban_user,
    get_moderator_stats,
    get_or_create_user,
    get_stats,
    get_user_info,
    list_moderators_with_users,
    remove_moderator,
    unban_user,
)
from utils.permissions import is_admin as _is_admin

from html import escape

router = Router(name="admin")


def _allowed_chat(message: Message) -> bool:
    """Команда разрешена только в личке с ботом или в чате модераторов."""
    settings = get_settings()
    return message.chat.type == "private" or message.chat.id == settings.moderator_chat_id


def _resolve_target_user_id(message: Message, command: CommandObject) -> tuple[int | None, str | None]:
    """Возвращает (user_id, error). Берёт ID либо из reply, либо из аргументов команды."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, None
    if not command.args:
        return None, texts.ADMIN_USER_ID_REQUIRED
    try:
        return int(command.args.strip().split()[0]), None
    except ValueError:
        return None, texts.ADMIN_BAD_USER_ID


def _admin_user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


async def _touch_caller(session: AsyncSession, message: Message) -> None:
    """Сохраняет/обновляет инфо о том, кто вызвал команду — чтобы /mods показывал ник админа."""
    if message.from_user is None:
        return
    await get_or_create_user(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )


@router.message(Command("admin"))
async def cmd_admin_help(message: Message, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    await session.commit()
    await message.answer(texts.ADMIN_HELP)


@router.message(Command("addmod"))
async def cmd_addmod(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    user_id, err = _resolve_target_user_id(message, command)
    if user_id is None:
        await message.answer(err or texts.ADMIN_USER_ID_REQUIRED)
        return
    # сохраним юзера в БД (имя/юзернейм) если есть в reply
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        await get_or_create_user(session, ru.id, ru.username, ru.full_name)
    await add_moderator(session, user_id)
    await session.commit()
    u, fn = await get_user_info(session, user_id)
    await message.reply(
        texts.ADMIN_MOD_ADDED.format(label=_format_mod_label(user_id, u, fn))
    )


@router.message(Command("delmod"))
async def cmd_delmod(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    user_id, err = _resolve_target_user_id(message, command)
    if user_id is None:
        await message.answer(err or texts.ADMIN_USER_ID_REQUIRED)
        return
    u, fn = await get_user_info(session, user_id)
    label = _format_mod_label(user_id, u, fn)
    removed = await remove_moderator(session, user_id)
    if not removed:
        await message.reply(texts.ADMIN_MOD_NOT_FOUND.format(label=label))
        return
    await session.commit()
    await message.reply(texts.ADMIN_MOD_REMOVED.format(label=label))


def _format_mod_label(user_id: int, username: str | None, full_name: str | None) -> str:
    parts: list[str] = []
    if username:
        parts.append(f"@{escape(username)}")
    if full_name:
        parts.append(escape(full_name))
    if not parts:
        # пользователь никогда не взаимодействовал с ботом и не был добавлен через reply
        return "(неизвестный пользователь)"
    return " — ".join(parts)


@router.message(Command("mods"))
async def cmd_list_mods(message: Message, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    await session.commit()
    mods = await list_moderators_with_users(session)
    settings = get_settings()
    lines_list: list[str] = []
    # сначала админы из ADMIN_IDS (они всегда модераторы)
    for admin_id in settings.admin_ids:
        u, fn = await get_user_info(session, admin_id)
        lines_list.append("✨ " + _format_mod_label(admin_id, u, fn) + " (admin)")
    for mid, u, fn in mods:
        if mid in settings.admin_ids:
            continue
        lines_list.append("- " + _format_mod_label(mid, u, fn))
    if not lines_list:
        await message.answer(texts.ADMIN_MODS_EMPTY)
        return
    await message.answer(texts.ADMIN_MODS_LIST.format(lines="\n".join(lines_list)))


@router.message(Command("modstats"))
async def cmd_modstats(message: Message, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    await session.commit()
    settings = get_settings()
    mods = await list_moderators_with_users(session)
    # собираем объединённый список (admins + appointed)
    by_id: dict[int, tuple[str | None, str | None]] = {}
    for admin_id in settings.admin_ids:
        u, fn = await get_user_info(session, admin_id)
        by_id[admin_id] = (u, fn)
    for mid, u, fn in mods:
        by_id.setdefault(mid, (u, fn))
    if not by_id:
        await message.answer(texts.ADMIN_MODS_EMPTY)
        return
    stats = await get_moderator_stats(session, list(by_id.keys()))
    lines: list[str] = []
    for mid, (u, fn) in by_id.items():
        s = stats.get(mid, {"accepted": 0, "rejected": 0})
        is_a = mid in settings.admin_ids
        prefix = "✨" if is_a else "•"
        suffix = " (admin)" if is_a else ""
        lines.append(
            f"{prefix} {_format_mod_label(mid, u, fn)}{suffix}\n"
            f"   ✅ принято: {s['accepted']}   ❌ отклонено: {s['rejected']}"
        )
    await message.answer(texts.ADMIN_MODSTATS.format(lines="\n\n".join(lines)))


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    # ID — из reply или из первого аргумента; причина — оставшийся текст
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        await get_or_create_user(session, ru.id, ru.username, ru.full_name)
        user_id = ru.id
        reason = command.args.strip() if command.args else None
    else:
        if not command.args:
            await message.answer(texts.ADMIN_USER_ID_REQUIRED)
            return
        parts = command.args.strip().split(maxsplit=1)
        try:
            user_id = int(parts[0])
        except ValueError:
            await message.answer(texts.ADMIN_BAD_USER_ID)
            return
        reason = parts[1] if len(parts) > 1 else None
    await ban_user(session, user_id, reason)
    await session.commit()
    u, fn = await get_user_info(session, user_id)
    await message.reply(texts.ADMIN_BANNED.format(label=_format_mod_label(user_id, u, fn)))


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    await _touch_caller(session, message)
    user_id, err = _resolve_target_user_id(message, command)
    if user_id is None:
        await message.answer(err or texts.ADMIN_USER_ID_REQUIRED)
        return
    u, fn = await get_user_info(session, user_id)
    label = _format_mod_label(user_id, u, fn)
    ok = await unban_user(session, user_id)
    if not ok:
        await message.reply(texts.ADMIN_BAN_NOT_FOUND.format(label=label))
        return
    await session.commit()
    await message.reply(texts.ADMIN_UNBANNED.format(label=label))


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession) -> None:
    if not _allowed_chat(message):
        return
    if not _is_admin(_admin_user_id(message) or 0):
        await message.answer(texts.ADMIN_ONLY)
        return
    stats = await get_stats(session)
    await message.answer(texts.ADMIN_STATS.format(**stats))
