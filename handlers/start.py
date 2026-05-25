"""Старт, главное меню, правила."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import get_settings
from db.queries import get_or_create_user
from keyboards.user import main_menu

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.chat.type != "private":
        # в группах /start игнорируем
        return
    await state.clear()
    user = message.from_user
    if user is not None:
        await get_or_create_user(session, user.id, user.username, user.full_name)

    settings = get_settings()
    intro = texts.START_GREETING
    if settings.rules_url:
        intro += f"\n\nПравила: {settings.rules_url}"
    await message.answer(intro, reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    await state.clear()
    await message.answer(texts.APPLICATION_CANCELLED, reply_markup=main_menu())


# Глобальный обработчик «❌ Отмена» — должен срабатывать независимо от FSM-состояния,
# в том числе когда состояние пустое (например, после рестарта сервиса состояние
# в памяти теряется, а у юзера на экране остаётся клавиатура с «Отмена»).
# Зарегистрирован в самом первом роутере, чтобы перехватывать кнопку раньше,
# чем шаги форм/вопросов попытаются её обработать.
@router.message(F.chat.type == "private", F.text == texts.BTN_CANCEL)
async def handle_cancel_button(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current and current.startswith("QuestionForm:"):
        text = texts.QUESTION_CANCEL
    elif current and current.startswith("ApplicationForm:"):
        text = texts.APPLICATION_CANCELLED
    else:
        text = "Главное меню:"
    await message.answer(text, reply_markup=main_menu())


@router.message(F.chat.type == "private", F.text == texts.BTN_RULES)
async def handle_rules(message: Message) -> None:
    settings = get_settings()
    if settings.rules_url:
        await message.answer(f"{texts.RULES_DEFAULT}\n\n{settings.rules_url}")
    else:
        await message.answer(texts.RULES_DEFAULT)
