"""Простое антифлуд-middleware. В памяти процесса хранит время последнего сообщения
для каждого пользователя. Если новое сообщение пришло раньше, чем через ANTIFLOOD_SECONDS,
оно блокируется (с одним вежливым ответом, чтобы не спамить)."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import texts
from config import get_settings


class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._last_action: dict[int, float] = {}
        self._notified: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings = get_settings()
        interval = settings.antiflood_seconds
        if interval <= 0:
            return await handler(event, data)

        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            # антифлуд применяем только к личке, чтобы не мешать модерационному чату
            if event.chat.type == "private":
                user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            # callback'и в обоих случаях
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        # админы и модераторы не флудятся
        if user_id in settings.admin_ids:
            return await handler(event, data)

        now = time.monotonic()
        last = self._last_action.get(user_id, 0.0)
        if now - last < interval:
            # уведомляем не чаще чем раз в интервал
            last_notify = self._notified.get(user_id, 0.0)
            if now - last_notify >= interval:
                self._notified[user_id] = now
                try:
                    if isinstance(event, Message):
                        await event.answer(texts.RATE_LIMITED)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(texts.RATE_LIMITED, show_alert=False)
                except Exception:
                    pass
            return None

        self._last_action[user_id] = now
        return await handler(event, data)
