"""Простое антифлуд-middleware. В памяти процесса хранит время последнего сообщения
для каждого пользователя. Если новое сообщение пришло раньше, чем через ANTIFLOOD_SECONDS,
оно блокируется (с одним вежливым ответом, чтобы не спамить)."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

import texts
from config import get_settings

# Тексты кнопок reply-клавиатур: их нажатия не должны попадать под антифлуд,
# иначе пользователь застревает в FSM, не может отменить шаг и т.п.
_MENU_BUTTONS: frozenset[str] = frozenset(
    {
        texts.BTN_SEND_APPLICATION,
        texts.BTN_ASK_QUESTION,
        texts.BTN_RULES,
        texts.BTN_SKIP,
        texts.BTN_PHOTOS_DONE,
        texts.BTN_PHOTOS_CLEAR,
        texts.BTN_CANCEL,
    }
)


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
                # нажатия на кнопки меню пропускаем мимо антифлуда — это навигация,
                # а не флуд: иначе юзер не может отменить шаг и считает, что бот висит
                if (event.text or "") in _MENU_BUTTONS:
                    return await handler(event, data)
                # если юзер сейчас в FSM (заполняет анкету или пишет вопрос) —
                # шаги формы тоже не должны попадать под антифлуд, иначе он
                # упирается в «слишком быстро» при быстром заполнении.
                state = data.get("state")
                if isinstance(state, FSMContext):
                    current_state = await state.get_state()
                    if current_state is not None:
                        return await handler(event, data)
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
