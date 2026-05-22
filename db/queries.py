"""Высокоуровневые функции работы с БД."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Application, ApplicationPhoto, ApplicationStatus, Moderator, Question, User


# --- Users ---

async def get_or_create_user(
    session: AsyncSession, user_id: int, username: str | None, full_name: str | None
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
    else:
        # обновляем username/full_name если изменились
        if user.username != username or user.full_name != full_name:
            user.username = username
            user.full_name = full_name
    return user


async def is_banned(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    return bool(user and user.is_banned)


async def ban_user(session: AsyncSession, user_id: int, reason: str | None) -> None:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, is_banned=True, ban_reason=reason)
        session.add(user)
    else:
        user.is_banned = True
        user.ban_reason = reason


async def unban_user(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is None or not user.is_banned:
        return False
    user.is_banned = False
    user.ban_reason = None
    return True


# --- Moderators ---

async def add_moderator(session: AsyncSession, user_id: int) -> bool:
    existing = await session.get(Moderator, user_id)
    if existing is not None:
        return False
    session.add(Moderator(user_id=user_id))
    return True


async def remove_moderator(session: AsyncSession, user_id: int) -> bool:
    existing = await session.get(Moderator, user_id)
    if existing is None:
        return False
    await session.delete(existing)
    return True


async def list_moderators(session: AsyncSession) -> list[int]:
    res = await session.execute(select(Moderator.user_id).order_by(Moderator.added_at))
    return list(res.scalars().all())


async def is_moderator(session: AsyncSession, user_id: int) -> bool:
    mod = await session.get(Moderator, user_id)
    return mod is not None


# --- Applications ---

async def count_approved_for_user(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(Application.id)).where(
            Application.user_id == user_id, Application.status == ApplicationStatus.APPROVED
        )
    )
    return int(res.scalar_one())


async def has_pending_application(session: AsyncSession, user_id: int) -> bool:
    res = await session.execute(
        select(func.count(Application.id)).where(
            Application.user_id == user_id, Application.status == ApplicationStatus.PENDING
        )
    )
    return int(res.scalar_one()) > 0


async def create_application(
    session: AsyncSession,
    user_id: int,
    username_at: str | None,
    name_surname: str,
    age_height: str,
    magic_abilities: str,
    character: str,
    biography: str,
    interesting_facts: str | None,
    work_position: str,
    place_of_living: str | None,
    roll: str,
    photo_file_ids: list[str],
) -> Application:
    app = Application(
        user_id=user_id,
        username_at=username_at,
        name_surname=name_surname,
        age_height=age_height,
        magic_abilities=magic_abilities,
        character=character,
        biography=biography,
        interesting_facts=interesting_facts,
        work_position=work_position,
        place_of_living=place_of_living,
        roll=roll,
        status=ApplicationStatus.PENDING,
    )
    session.add(app)
    await session.flush()
    for idx, file_id in enumerate(photo_file_ids):
        session.add(ApplicationPhoto(application_id=app.id, file_id=file_id, position=idx))
    await session.flush()
    return app


async def get_application(session: AsyncSession, app_id: int) -> Application | None:
    res = await session.execute(
        select(Application).where(Application.id == app_id).options(selectinload(Application.photos))
    )
    return res.scalar_one_or_none()


async def set_application_mod_message(
    session: AsyncSession, app_id: int, chat_id: int, message_id: int
) -> None:
    await session.execute(
        update(Application)
        .where(Application.id == app_id)
        .values(mod_chat_id=chat_id, mod_message_id=message_id)
    )


async def approve_application(
    session: AsyncSession,
    app_id: int,
    channel_message_id: int | None,
    moderator_id: int | None = None,
) -> Application | None:
    app = await get_application(session, app_id)
    if app is None or app.status != ApplicationStatus.PENDING:
        return None
    app.status = ApplicationStatus.APPROVED
    app.channel_message_id = channel_message_id
    app.moderated_by_user_id = moderator_id
    return app


async def reject_application(
    session: AsyncSession,
    app_id: int,
    reason: str,
    moderator_id: int | None = None,
) -> Application | None:
    app = await get_application(session, app_id)
    if app is None or app.status != ApplicationStatus.PENDING:
        return None
    app.status = ApplicationStatus.REJECTED
    app.reject_reason = reason
    app.moderated_by_user_id = moderator_id
    return app


async def list_moderators_with_users(
    session: AsyncSession,
) -> list[tuple[int, str | None, str | None]]:
    """Возвращает [(user_id, username, full_name), ...] из таблицы Moderator + JOIN User."""
    res = await session.execute(
        select(Moderator.user_id, User.username, User.full_name)
        .select_from(Moderator)
        .outerjoin(User, User.id == Moderator.user_id)
        .order_by(Moderator.added_at)
    )
    return [(int(r[0]), r[1], r[2]) for r in res.all()]


async def get_user_info(
    session: AsyncSession, user_id: int
) -> tuple[str | None, str | None]:
    """Возвращает (username, full_name) или (None, None)."""
    user = await session.get(User, user_id)
    if user is None:
        return None, None
    return user.username, user.full_name


async def get_moderator_stats(
    session: AsyncSession, mod_ids: list[int]
) -> dict[int, dict[str, int]]:
    """Для каждого user_id возвращает {accepted, rejected}."""
    if not mod_ids:
        return {}
    res = await session.execute(
        select(
            Application.moderated_by_user_id,
            Application.status,
            func.count(Application.id),
        )
        .where(Application.moderated_by_user_id.in_(mod_ids))
        .group_by(Application.moderated_by_user_id, Application.status)
    )
    out: dict[int, dict[str, int]] = {mid: {"accepted": 0, "rejected": 0} for mid in mod_ids}
    for mid, status, cnt in res.all():
        if mid is None:
            continue
        bucket = out.setdefault(int(mid), {"accepted": 0, "rejected": 0})
        if status == ApplicationStatus.APPROVED:
            bucket["accepted"] = int(cnt)
        elif status == ApplicationStatus.REJECTED:
            bucket["rejected"] = int(cnt)
    return out


# --- Stats ---

async def get_stats(session: AsyncSession) -> dict[str, int]:
    total = int((await session.execute(select(func.count(Application.id)))).scalar_one())
    pending = int(
        (
            await session.execute(
                select(func.count(Application.id)).where(Application.status == ApplicationStatus.PENDING)
            )
        ).scalar_one()
    )
    approved = int(
        (
            await session.execute(
                select(func.count(Application.id)).where(Application.status == ApplicationStatus.APPROVED)
            )
        ).scalar_one()
    )
    rejected = int(
        (
            await session.execute(
                select(func.count(Application.id)).where(Application.status == ApplicationStatus.REJECTED)
            )
        ).scalar_one()
    )
    users = int((await session.execute(select(func.count(User.id)))).scalar_one())
    banned = int(
        (
            await session.execute(select(func.count(User.id)).where(User.is_banned.is_(True)))
        ).scalar_one()
    )
    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "users": users,
        "banned": banned,
    }


# --- Questions ---

async def create_question(session: AsyncSession, user_id: int, text: str) -> Question:
    q = Question(user_id=user_id, text=text)
    session.add(q)
    await session.flush()
    return q


async def set_question_mod_message(
    session: AsyncSession, q_id: int, chat_id: int, message_id: int
) -> None:
    await session.execute(
        update(Question)
        .where(Question.id == q_id)
        .values(mod_chat_id=chat_id, mod_message_id=message_id)
    )


async def answer_question(session: AsyncSession, q_id: int, answer: str) -> Question | None:
    q = await session.get(Question, q_id)
    if q is None or q.answered:
        return None
    q.answered = True
    q.answer_text = answer
    return q


async def get_question(session: AsyncSession, q_id: int) -> Question | None:
    return await session.get(Question, q_id)
