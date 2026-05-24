"""Раздел «Задать вопрос»: пользователь пишет вопрос, модераторы отвечают."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import get_settings
from db.queries import (
    answer_question,
    create_question,
    get_or_create_user,
    get_question,
    set_question_mod_message,
)
from keyboards.moderator import question_kb
from keyboards.user import cancel_kb, main_menu
from states.moderation import ModerationFlow
from states.question import QuestionForm
from utils.formatting import user_link
from utils.permissions import is_authorized_moderator

logger = logging.getLogger(__name__)
router = Router(name="question")

QUESTION_MAX = 2000


def _is_mod_chat(chat_id: int) -> bool:
    return chat_id == get_settings().moderator_chat_id


@router.message(F.chat.type == "private", F.text == texts.BTN_ASK_QUESTION)
async def start_question(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(QuestionForm.waiting_text)
    await message.answer(texts.ASK_QUESTION_PROMPT, reply_markup=cancel_kb())


@router.message(QuestionForm.waiting_text, F.text == texts.BTN_CANCEL)
async def cancel_question(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.QUESTION_CANCEL, reply_markup=main_menu())


@router.message(QuestionForm.waiting_text, F.text)
async def question_received(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if message.from_user is None:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer(texts.ASK_QUESTION_PROMPT)
        return
    if len(text) > QUESTION_MAX:
        await message.answer(f"Слишком длинное сообщение (макс. {QUESTION_MAX} символов).")
        return

    try:
        html_body = (message.html_text or "").strip() or text
    except (AttributeError, TypeError):
        html_body = text

    await get_or_create_user(session, message.from_user.id, message.from_user.username, message.from_user.full_name)
    q = await create_question(session, message.from_user.id, html_body)
    await session.commit()

    settings = get_settings()
    header = texts.MOD_QUESTION_HEADER.format(
        q_id=q.id,
        user_link=user_link(message.from_user),
        user_id=message.from_user.id,
    )
    try:
        sent = await bot.send_message(
            chat_id=settings.moderator_chat_id,
            text=f"{header}\n{html_body}",
            reply_markup=question_kb(q.id),
        )
        await set_question_mod_message(session, q.id, sent.chat.id, sent.message_id)
        await session.commit()
    except TelegramAPIError as e:
        logger.exception("Failed to send question to moderators: %s", e)
        await message.answer(texts.ERROR_GENERIC, reply_markup=main_menu())
        await state.clear()
        return

    await state.clear()
    await message.answer(texts.QUESTION_SENT, reply_markup=main_menu())


@router.callback_query(F.data.startswith("q:answer:"))
async def cb_answer(
    call: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not isinstance(call.message, Message) or not _is_mod_chat(call.message.chat.id):
        await call.answer()
        return
    if call.data is None or call.from_user is None:
        await call.answer()
        return
    if not await is_authorized_moderator(session, call.from_user.id):
        await call.answer(texts.MOD_NOT_AUTHORIZED, show_alert=True)
        return
    try:
        q_id = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    q = await get_question(session, q_id)
    if q is None or q.answered:
        await call.answer("Этот вопрос уже отвечен.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        return

    prompt = await call.message.reply(
        texts.MOD_ANSWER_PROMPT.format(q_id=q_id),
        reply_markup=ForceReply(selective=True, input_field_placeholder="Ответ пользователю"),
    )
    await state.set_state(ModerationFlow.awaiting_answer)
    await state.update_data(q_id=q_id, prompt_message_id=prompt.message_id)
    await call.answer()


@router.message(ModerationFlow.awaiting_answer, F.reply_to_message)
async def answer_received(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if not _is_mod_chat(message.chat.id):
        return
    if message.from_user is None or not await is_authorized_moderator(session, message.from_user.id):
        return
    data = await state.get_data()
    expected_prompt_id = data.get("prompt_message_id")
    q_id = data.get("q_id")
    if (
        message.reply_to_message is None
        or expected_prompt_id is None
        or message.reply_to_message.message_id != expected_prompt_id
        or q_id is None
    ):
        return

    answer_text = (message.text or "").strip()
    if not answer_text:
        await message.reply("Ответ не должен быть пустым.")
        return

    try:
        answer_html = (message.html_text or "").strip() or answer_text
    except (AttributeError, TypeError):
        answer_html = answer_text

    q = await answer_question(session, int(q_id), answer_html)
    if q is None:
        await state.clear()
        await message.reply("Этот вопрос уже отвечен.")
        return
    await session.commit()

    await state.clear()
    try:
        await bot.send_message(
            chat_id=q.user_id,
            text=texts.USER_ANSWER_HEADER.format(answer=answer_html),
        )
        await message.reply(texts.MOD_ANSWER_OK)
        # убираем кнопку «Ответить» с исходной карточки
        if q.mod_chat_id and q.mod_message_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=q.mod_chat_id, message_id=q.mod_message_id, reply_markup=None
                )
            except TelegramAPIError:
                pass
    except TelegramAPIError as e:
        logger.warning("Failed to deliver answer to user %s: %s", q.user_id, e)
        await message.reply(texts.MOD_USER_NOTIFY_FAILED.format(error=str(e)[:100]))
