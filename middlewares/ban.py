"""Middleware, который блокирует забаненных пользователей."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import texts
from db.base import get_session_factory
from db.queries import is_banned


class BanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user and event.chat.type == "private":
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            # запрещаем нажимать кнопки тоже
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        session_factory = get_session_factory()
        async with session_factory() as session:
            banned = await is_banned(session, user_id)

        if banned:
            try:
                if isinstance(event, Message):
                    await event.answer(texts.USER_BANNED)
                elif isinstance(event, CallbackQuery):
                    await event.answer(texts.USER_BANNED, show_alert=True)
            except Exception:
                pass
            return None

        return await handler(event, data)
