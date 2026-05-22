"""Middleware для склейки сообщений из media_group в один список.

aiogram присылает каждое фото из альбома как отдельный update. Чтобы хэндлеры могли
работать с альбомом как единым целым, мы:
- собираем сообщения с одинаковым media_group_id в буфер;
- после короткой задержки прокидываем все собранные сообщения первому хэндлеру
  через data["album"] (список Message), а последующие апдейты того же альбома
  не передаются дальше.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.7) -> None:
        super().__init__()
        self.latency = latency
        self._albums: dict[str, list[Message]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        group_id = event.media_group_id
        lock = self._locks.setdefault(group_id, asyncio.Lock())
        async with lock:
            is_first = group_id not in self._albums
            self._albums.setdefault(group_id, []).append(event)

        if not is_first:
            # последующие сообщения этой же группы — не обрабатываем
            return None

        # ждём пока подтянутся остальные сообщения группы
        await asyncio.sleep(self.latency)
        messages = self._albums.pop(group_id, [event])
        self._locks.pop(group_id, None)
        data["album"] = sorted(messages, key=lambda m: m.message_id)
        return await handler(event, data)
