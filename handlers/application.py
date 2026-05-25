"""FSM заполнения анкеты + предпросмотр + отправка модераторам."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

import texts
from config import get_settings
from db.queries import (
    count_approved_for_user,
    create_application,
    get_or_create_user,
    has_pending_application,
    set_application_mod_message,
)
from keyboards.moderator import moderation_kb
from keyboards.user import (
    cancel_kb,
    main_menu,
    photos_kb,
    preview_kb,
    remove_kb,
    skip_cancel_kb,
)
from states.application import ApplicationForm
from utils.formatting import render_application, user_link
from utils.messaging import send_application_messages

logger = logging.getLogger(__name__)
router = Router(name="application")


async def _start_application_flow(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = message.from_user
    if user is None:
        return
    settings = get_settings()
    await get_or_create_user(session, user.id, user.username, user.full_name)

    if await has_pending_application(session, user.id):
        await message.answer(texts.PENDING_EXISTS, reply_markup=main_menu())
        return

    approved = await count_approved_for_user(session, user.id)
    if approved >= settings.max_approved_per_user:
        await message.answer(
            texts.LIMIT_APPROVED_REACHED.format(limit=settings.max_approved_per_user),
            reply_markup=main_menu(),
        )
        return

    await state.clear()
    await state.set_state(ApplicationForm.name_surname)
    await message.answer(texts.ASK_NAME_SURNAME, reply_markup=cancel_kb())


@router.message(F.chat.type == "private", F.text == texts.BTN_SEND_APPLICATION)
async def handle_send_btn(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _start_application_flow(message, state, session)


@router.callback_query(F.data == "resend:yes")
async def handle_resend_yes(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await _start_application_flow(call.message, state, session)


@router.callback_query(F.data == "resend:no")
async def handle_resend_no(call: CallbackQuery) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await call.message.answer(texts.APPLICATION_CANCELLED, reply_markup=main_menu())


# --- Универсальная отмена внутри FSM ---


@router.message(StateFilter(ApplicationForm), F.text == texts.BTN_CANCEL)
async def cancel_in_form(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.APPLICATION_CANCELLED, reply_markup=main_menu())


# --- Шаги анкеты ---


def _validate_text(value: str, *, limit: int, min_len: int = 1) -> tuple[bool, str | None]:
    """Возвращает (ok, error_message)."""
    if len(value) < min_len:
        if min_len == 1:
            return False, texts.NAME_EMPTY
        return False, texts.BIOGRAPHY_TOO_SHORT.format(actual=len(value))
    if len(value) > limit:
        return False, texts.NAME_TOO_LONG.format(limit=limit)
    return True, None


def _capture(message: Message) -> tuple[str, str]:
    """Возвращает (visible_text, html_text).

    visible_text — для валидации длины (видимые символы).
    html_text — для хранения и публикации (сохраняет премиум-эмодзи, ссылки, форматирование).
    """
    visible = (message.text or "").strip()
    if not visible:
        return "", ""
    try:
        html = (message.html_text or "").strip()
    except (AttributeError, TypeError):
        html = visible
    return visible, html


async def _remember_origin(message: Message, state: FSMContext, field: str) -> None:
    """Запоминает chat_id и message_id поля в FSM, чтобы при публикации в канал
    можно было скопировать оригинальное сообщение вместе с его custom_emoji entities.
    """
    data = await state.get_data()
    field_msg_ids: dict[str, int] = dict(data.get("_field_msg_ids") or {})
    field_msg_ids[field] = message.message_id
    await state.update_data(_field_msg_ids=field_msg_ids, _user_chat_id=message.chat.id)


@router.message(ApplicationForm.name_surname, F.text)
async def step_name_surname(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.NAME_SURNAME_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(name_surname=html)
    await _remember_origin(message, state, "name_surname")
    await state.set_state(ApplicationForm.age_height)
    await message.answer(texts.ASK_AGE_HEIGHT, reply_markup=cancel_kb())


@router.message(ApplicationForm.age_height, F.text)
async def step_age_height(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.AGE_HEIGHT_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(age_height=html)
    await _remember_origin(message, state, "age_height")
    await state.set_state(ApplicationForm.magic_abilities)
    await message.answer(texts.ASK_MAGIC, reply_markup=cancel_kb())


@router.message(ApplicationForm.magic_abilities, F.text)
async def step_magic(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.MAGIC_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(magic_abilities=html)
    await _remember_origin(message, state, "magic_abilities")
    await state.set_state(ApplicationForm.character)
    await message.answer(texts.ASK_CHARACTER, reply_markup=cancel_kb())


@router.message(ApplicationForm.character, F.text)
async def step_character(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.CHARACTER_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(character=html)
    await _remember_origin(message, state, "character")
    await state.set_state(ApplicationForm.biography)
    await message.answer(texts.ASK_BIOGRAPHY, reply_markup=cancel_kb())


@router.message(ApplicationForm.biography, F.text)
async def step_biography(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.BIOGRAPHY_MAX, min_len=texts.BIOGRAPHY_MIN)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(biography=html)
    await _remember_origin(message, state, "biography")
    await state.set_state(ApplicationForm.interesting_facts)
    await message.answer(texts.ASK_FACTS, reply_markup=skip_cancel_kb())


@router.message(ApplicationForm.interesting_facts, F.text == texts.BTN_SKIP)
async def step_facts_skip(message: Message, state: FSMContext) -> None:
    await state.update_data(interesting_facts=None)
    await state.set_state(ApplicationForm.work_position)
    await message.answer(texts.ASK_WORK, reply_markup=cancel_kb())


@router.message(ApplicationForm.interesting_facts, F.text)
async def step_facts(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.FACTS_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(interesting_facts=html)
    await _remember_origin(message, state, "interesting_facts")
    await state.set_state(ApplicationForm.work_position)
    await message.answer(texts.ASK_WORK, reply_markup=cancel_kb())


@router.message(ApplicationForm.work_position, F.text)
async def step_work(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.WORK_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(work_position=html)
    await _remember_origin(message, state, "work_position")
    await state.set_state(ApplicationForm.place_of_living)
    await message.answer(texts.ASK_PLACE, reply_markup=skip_cancel_kb())


@router.message(ApplicationForm.place_of_living, F.text == texts.BTN_SKIP)
async def step_place_skip(message: Message, state: FSMContext) -> None:
    await state.update_data(place_of_living=None)
    await state.set_state(ApplicationForm.roll)
    await message.answer(texts.ASK_ROLL, reply_markup=cancel_kb())


@router.message(ApplicationForm.place_of_living, F.text)
async def step_place(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.PLACE_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(place_of_living=html)
    await _remember_origin(message, state, "place_of_living")
    await state.set_state(ApplicationForm.roll)
    await message.answer(texts.ASK_ROLL, reply_markup=cancel_kb())


@router.message(ApplicationForm.roll, F.text)
async def step_roll(message: Message, state: FSMContext) -> None:
    text, html = _capture(message)
    ok, err = _validate_text(text, limit=texts.ROLL_MAX)
    if not ok:
        await message.answer(err or texts.ERROR_GENERIC)
        return
    await state.update_data(roll=html)
    await _remember_origin(message, state, "roll")
    settings = get_settings()
    await state.update_data(photos=[])
    await state.set_state(ApplicationForm.photos)
    await message.answer(
        texts.ASK_PHOTOS.format(min_photos=settings.min_photos, max_photos=settings.max_photos),
        reply_markup=photos_kb(),
    )


# --- Фото ---


@router.message(ApplicationForm.photos, F.text == texts.BTN_PHOTOS_CLEAR)
async def step_photos_clear(message: Message, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await message.answer(texts.PHOTOS_CLEARED, reply_markup=photos_kb())


@router.message(ApplicationForm.photos, F.photo)
async def step_photos_add(
    message: Message, state: FSMContext, album: list[Message] | None = None
) -> None:
    settings = get_settings()
    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])

    messages = album if album else [message]
    added = 0
    for msg in messages:
        if not msg.photo:
            continue
        if len(photos) >= settings.max_photos:
            break
        photos.append(msg.photo[-1].file_id)
        added += 1

    await state.update_data(photos=photos)

    if added == 0:
        await message.answer(texts.PHOTO_LIMIT_REACHED.format(max_photos=settings.max_photos))
        return

    if len(photos) >= settings.max_photos:
        await message.answer(
            f"Загружено {len(photos)}/{settings.max_photos} фото. Достигнут максимум. "
            f"Нажмите «Готово»."
        )
    else:
        await message.answer(texts.PHOTO_ADDED.format(count=len(photos), max_photos=settings.max_photos))


@router.message(ApplicationForm.photos, F.text == texts.BTN_PHOTOS_DONE)
async def step_photos_done(message: Message, state: FSMContext, bot: Bot) -> None:
    settings = get_settings()
    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])
    if len(photos) < settings.min_photos:
        await message.answer(
            texts.PHOTO_NOT_ENOUGH.format(min_photos=settings.min_photos, count=len(photos))
        )
        return
    await _send_preview(message, state, bot)


@router.message(ApplicationForm.photos)
async def step_photos_other(message: Message) -> None:
    """Любое другое сообщение на шаге фото — подсказка."""
    await message.answer(texts.PHOTO_ONLY)


# --- Предпросмотр ---


def _build_body_from_state(data: dict, username: str | None) -> str:
    return render_application(
        name_surname=str(data["name_surname"]),
        age_height=str(data["age_height"]),
        magic_abilities=str(data["magic_abilities"]),
        character=str(data["character"]),
        biography=str(data["biography"]),
        interesting_facts=data.get("interesting_facts"),
        work_position=str(data["work_position"]),
        place_of_living=data.get("place_of_living"),
        roll=str(data["roll"]),
        username=username,
    )


async def _send_preview(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])
    user = message.from_user
    username = user.username if user else None

    body = _build_body_from_state(data, username)
    preview_text = f"{texts.PREVIEW_HEADER}\n\n{body}"

    await send_application_messages(bot, message.chat.id, preview_text, photos)
    # снимаем reply-клавиатуру с шага «фото» и показываем инлайн-подтверждение
    await message.answer("👇", reply_markup=remove_kb())
    await state.set_state(ApplicationForm.preview)
    await message.answer(texts.PREVIEW_CONFIRM, reply_markup=preview_kb())


@router.callback_query(ApplicationForm.preview, F.data == "preview:edit")
async def preview_edit(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    await state.set_state(ApplicationForm.name_surname)
    if isinstance(call.message, Message):
        await call.message.answer(texts.ASK_NAME_SURNAME, reply_markup=cancel_kb())


@router.callback_query(ApplicationForm.preview, F.data == "preview:cancel")
async def preview_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await call.message.answer(texts.APPLICATION_CANCELLED, reply_markup=main_menu())


@router.callback_query(ApplicationForm.preview, F.data == "preview:send")
async def preview_send(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await call.answer()
    if call.from_user is None or not isinstance(call.message, Message):
        return

    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])
    settings = get_settings()

    if await has_pending_application(session, call.from_user.id):
        await call.message.answer(texts.PENDING_EXISTS, reply_markup=main_menu())
        await state.clear()
        return
    if await count_approved_for_user(session, call.from_user.id) >= settings.max_approved_per_user:
        await call.message.answer(
            texts.LIMIT_APPROVED_REACHED.format(limit=settings.max_approved_per_user),
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    await get_or_create_user(session, call.from_user.id, call.from_user.username, call.from_user.full_name)
    username_at = call.from_user.username

    field_msg_ids_raw = data.get("_field_msg_ids") or {}
    field_msg_ids: dict[str, int] = {
        str(k): int(v) for k, v in field_msg_ids_raw.items() if isinstance(v, int)
    }
    user_chat_id_raw = data.get("_user_chat_id")
    user_chat_id: int | None = int(user_chat_id_raw) if isinstance(user_chat_id_raw, int) else None

    app = await create_application(
        session,
        user_id=call.from_user.id,
        username_at=username_at,
        name_surname=str(data["name_surname"]),
        age_height=str(data["age_height"]),
        magic_abilities=str(data["magic_abilities"]),
        character=str(data["character"]),
        biography=str(data["biography"]),
        interesting_facts=data.get("interesting_facts"),
        work_position=str(data["work_position"]),
        place_of_living=data.get("place_of_living"),
        roll=str(data["roll"]),
        photo_file_ids=photos,
        user_chat_id=user_chat_id,
        field_message_ids=field_msg_ids,
    )
    await session.commit()

    body = _build_body_from_state(data, username_at)
    header = texts.MOD_APPLICATION_HEADER.format(
        app_id=app.id,
        user_link=user_link(call.from_user),
        user_id=call.from_user.id,
    )
    mod_body = f"{header}\n{body}"

    try:
        _ids, last_text_id = await send_application_messages(
            bot,
            settings.moderator_chat_id,
            mod_body,
            photos,
            final_reply_markup=moderation_kb(app.id),
        )
        if last_text_id is not None:
            await set_application_mod_message(session, app.id, settings.moderator_chat_id, last_text_id)
    except TelegramAPIError as e:
        logger.exception("Failed to send to moderators: %s", e)
        await call.message.answer(texts.ERROR_GENERIC, reply_markup=main_menu())
        await state.clear()
        return

    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await call.message.answer(texts.APPLICATION_SENT, reply_markup=main_menu())
