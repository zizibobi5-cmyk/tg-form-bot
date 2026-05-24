"""ORM-модели."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChannelPublicationStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user_id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ban_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    applications: Mapped[list["Application"]] = relationship(back_populates="user")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    # фактический Telegram-юзернейм пользователя на момент подачи (для «Юзернейм:» в публикации)
    username_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    name_surname: Mapped[str] = mapped_column(Text, nullable=False)
    age_height: Mapped[str] = mapped_column(Text, nullable=False)
    magic_abilities: Mapped[str] = mapped_column(Text, nullable=False)
    character: Mapped[str] = mapped_column(Text, nullable=False)
    biography: Mapped[str] = mapped_column(Text, nullable=False)
    interesting_facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_position: Mapped[str] = mapped_column(Text, nullable=False)
    place_of_living: Mapped[str | None] = mapped_column(Text, nullable=True)
    roll: Mapped[str] = mapped_column(Text, nullable=False)

    # ID приватного чата с ботом и message_id каждого поля анкеты в формате JSON
    # ({field_name: message_id, ...}). Нужны, чтобы при публикации в канал можно было
    # скопировать оригинальные сообщения через copy_message — это сохраняет премиум-эмодзи,
    # которые иначе режутся при отправке ботом в канал.
    user_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    field_message_ids: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=16),
        default=ApplicationStatus.PENDING,
        nullable=False,
        index=True,
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # кто принял/отклонил эту анкету (для статистики модераторов)
    moderated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    mod_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mod_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="applications")
    photos: Mapped[list["ApplicationPhoto"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationPhoto.position"
    )


class ApplicationPhoto(Base):
    __tablename__ = "application_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    application: Mapped["Application"] = relationship(back_populates="photos")


class Moderator(Base):
    """Дополнительные модераторы. Любой участник MODERATOR_CHAT_ID и так считается модератором,
    но через эту таблицу можно дать права в личке."""
    __tablename__ = "moderators"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    mod_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mod_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ChannelPublication(Base):
    """Очередь публикаций в Telegram-канал, обслуживаемая Telethon-юзерботом.

    Анкетный бот при принятии анкеты модератором кладёт сюда задачу, а
    отдельный сервис ``userbot.main`` (Telethon, логин под Premium-аккаунтом)
    забирает её и публикует в канал — это сохраняет премиум-эмодзи, которые
    Telegram режет у сообщений ботов.
    """

    __tablename__ = "channel_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ChannelPublicationStatus] = mapped_column(
        Enum(ChannelPublicationStatus, native_enum=False, length=16),
        default=ChannelPublicationStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # время, когда воркер захватил задачу: используется для детекции зависших задач
    # (если задача застряла в in_progress дольше TTL — её можно вернуть в pending).
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    photos: Mapped[list["ChannelPublicationPhoto"]] = relationship(
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="ChannelPublicationPhoto.position",
    )


class ChannelPublicationPhoto(Base):
    """Бинарные данные фото для публикации. Бот скачивает оригинал через bot.get_file
    и кладёт байты сюда, потому что Bot API file_id не работают в Telethon (MTProto)."""

    __tablename__ = "channel_publication_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    publication: Mapped["ChannelPublication"] = relationship(back_populates="photos")
