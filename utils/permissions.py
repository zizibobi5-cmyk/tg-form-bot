"""Проверка прав модератора/админа."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.queries import is_moderator as _is_moderator_in_db


async def is_authorized_moderator(session: AsyncSession, user_id: int) -> bool:
    """True если пользователь — админ из ADMIN_IDS или явно добавлен в таблицу модераторов."""
    if user_id in get_settings().admin_ids:
        return True
    return await _is_moderator_in_db(session, user_id)


def is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids
