"""Хэндлеры модерации анкет."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import get_settings
from db.models import ApplicationStatus
from db.queries import (
    approve_application,
    ban_user,
    enqueue_channel_publication,
    get_application,
    reject_application,
)
from keyboards.user import resend_kb
from states.moderation import ModerationFlow
from utils.formatting import render_application
from utils.messaging import send_application_messages
from utils.permissions import is_authorized_moderator

logger = logging.getLogger(__name__)
router = Router(name="moderation")


def _is_mod_chat(chat_id: int) -> bool:
    return chat_id == get_settings().moderator_chat_id


async def _download_photos(bot: Bot, photo_file_ids: list[str]) -> list[bytes]:
    """Скачивает байты фото из Bot API. Нужно, чтобы передать их юзерботу через БД:
    Bot API file_id не работают в MTProto/Telethon, поэтому шлём raw bytes.
    """
    import io as _io

    blobs: list[bytes] = []
    for fid in photo_file_ids:
        buf = _io.BytesIO()
        await bot.download(fid, destination=buf)
        blobs.append(buf.getvalue())
    return blobs


@router.callback_query(F.data.startswith("mod:accept:"))
async def cb_accept(
    call: CallbackQuery, session: AsyncSession, bot: Bot
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
        app_id = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    app = await get_application(session, app_id)
    if app is None or app.status != ApplicationStatus.PENDING:
        await call.answer(texts.MOD_ALREADY_PROCESSED, show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        return

    settings = get_settings()
    body = render_application(
        name_surname=app.name_surname,
        age_height=app.age_height,
        magic_abilities=app.magic_abilities,
        character=app.character,
        biography=app.biography,
        interesting_facts=app.interesting_facts,
        work_position=app.work_position,
        place_of_living=app.place_of_living,
        roll=app.roll,
        username=app.username_at,
    )
    photo_ids = [p.file_id for p in app.photos]

    channel_message_id: int | None = None
    if settings.userbot_enabled:
        # Новый путь: публикует Telethon-юзербот отдельным сервисом.
        # Кладём в очередь, скачав байты фото из Bot API (file_id Bot API не работают
        # в MTProto). channel_message_id будет проставлен юзерботом после фактической
        # публикации.
        try:
            photo_blobs = await _download_photos(bot, photo_ids)
        except TelegramAPIError as e:
            logger.exception("Failed to download photos for queueing: %s", e)
            await call.answer(texts.MOD_PUBLISH_FAILED.format(error=str(e)[:100]), show_alert=True)
            return
        await enqueue_channel_publication(
            session,
            application_id=app_id,
            body_html=body,
            photo_bytes=photo_blobs,
        )
    else:
        # Старый путь (fallback, когда USERBOT_ENABLED=0): бот сам публикует в канал,
        # но премиум-эмодзи будут резаться (это ограничение Telegram для ботов).
        try:
            sent_ids, _ = await send_application_messages(
                bot,
                settings.channel_id,
                body,
                photo_ids,
                text_first=True,
                delay_between_texts=settings.channel_delay_between_texts,
                delay_before_photos=settings.channel_delay_before_photos,
            )
            if sent_ids:
                channel_message_id = sent_ids[0]
        except TelegramAPIError as e:
            logger.exception("Failed to publish to channel: %s", e)
            await call.answer(texts.MOD_PUBLISH_FAILED.format(error=str(e)[:100]), show_alert=True)
            return

    await approve_application(session, app_id, channel_message_id, moderator_id=call.from_user.id)
    await session.commit()

    try:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.reply(texts.MOD_ACCEPTED_OK.format(app_id=app_id))
    except TelegramAPIError:
        pass

    await call.answer("OK")

    # уведомляем пользователя
    try:
        await bot.send_message(chat_id=app.user_id, text=texts.USER_ACCEPTED)
    except TelegramAPIError as e:
        logger.warning("Failed to notify user %s: %s", app.user_id, e)


@router.callback_query(F.data.startswith("mod:reject:"))
async def cb_reject(
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
        app_id = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    app = await get_application(session, app_id)
    if app is None or app.status != ApplicationStatus.PENDING:
        await call.answer(texts.MOD_ALREADY_PROCESSED, show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        return

    prompt = await call.message.reply(
        texts.MOD_ASK_REJECT_REASON.format(app_id=app_id),
        reply_markup=ForceReply(selective=True, input_field_placeholder="Причина отказа"),
    )
    await state.set_state(ModerationFlow.awaiting_reject_reason)
    await state.update_data(app_id=app_id, prompt_message_id=prompt.message_id)
    await call.answer()


@router.message(ModerationFlow.awaiting_reject_reason, F.reply_to_message)
async def reject_reason_received(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if not _is_mod_chat(message.chat.id):
        return
    if message.from_user is None or not await is_authorized_moderator(session, message.from_user.id):
        return
    data = await state.get_data()
    expected_prompt_id = data.get("prompt_message_id")
    app_id = data.get("app_id")
    if (
        message.reply_to_message is None
        or expected_prompt_id is None
        or message.reply_to_message.message_id != expected_prompt_id
        or app_id is None
    ):
        return

    reason = (message.text or "").strip()
    if not reason:
        await message.reply("Причина не должна быть пустой. Ответьте на запрос ещё раз.")
        return

    app = await reject_application(
        session, int(app_id), reason, moderator_id=message.from_user.id if message.from_user else None
    )
    if app is None:
        await state.clear()
        await message.reply(texts.MOD_ALREADY_PROCESSED)
        return
    await session.commit()

    await state.clear()
    await message.reply(texts.MOD_REJECTED_OK.format(app_id=app_id))

    # уведомляем пользователя
    try:
        await bot.send_message(chat_id=app.user_id, text=texts.USER_REJECTED.format(reason=reason))
        await bot.send_message(
            chat_id=app.user_id,
            text=texts.USER_REJECTED_RESEND_PROMPT,
            reply_markup=resend_kb(),
        )
    except TelegramAPIError as e:
        logger.warning("Failed to notify user %s about rejection: %s", app.user_id, e)
        try:
            await message.reply(texts.MOD_USER_NOTIFY_FAILED.format(error=str(e)[:100]))
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("mod:ban:"))
async def cb_ban_user(
    call: CallbackQuery, session: AsyncSession, bot: Bot
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
        app_id = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    app = await get_application(session, app_id)
    if app is None:
        await call.answer(texts.MOD_ALREADY_PROCESSED, show_alert=True)
        return

    await ban_user(session, app.user_id, reason="Забанен модератором при отклонении анкеты")
    if app.status == ApplicationStatus.PENDING:
        await reject_application(
            session, app_id, "Пользователь заблокирован", moderator_id=call.from_user.id
        )
    await session.commit()

    try:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.reply(f"Пользователь {app.user_id} забанен. Анкета #{app_id} отклонена.")
    except TelegramAPIError:
        pass

    await call.answer("OK")

    try:
        await bot.send_message(chat_id=app.user_id, text=texts.USER_BANNED)
    except TelegramAPIError as e:
        logger.warning("Failed to notify banned user %s: %s", app.user_id, e)
