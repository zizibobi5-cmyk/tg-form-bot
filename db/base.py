"""Подключение к БД и фабрика сессий SQLAlchemy."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей."""


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        kwargs: dict = {"echo": False, "future": True}
        if not settings.is_sqlite:
            # Neon и большинство Postgres-хостингов разрывают idle-соединения;
            # pre_ping предотвращает ошибки типа SSL closed unexpectedly.
            kwargs.update(
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=5,
                max_overflow=5,
            )
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


async def init_db() -> None:
    """Создаёт таблицы, если их ещё нет, и подтягивает простые миграции схемы."""
    # импорт нужен, чтобы модели зарегистрировались в metadata
    from db import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Миграция: в старых развёртываниях name_surname/age_height имели VARCHAR(256),
        # но HTML-форматированный текст (премиум-эмодзи) бывает длиннее. На Postgres
        # расширяем колонки до TEXT. На SQLite VARCHAR(N) не ограничивает длину,
        # поэтому миграция нужна только для PG.
        backend = engine.url.get_backend_name()
        if backend.startswith("postgres"):
            from sqlalchemy import text as _sql_text
            for col in ("name_surname", "age_height"):
                await conn.execute(
                    _sql_text(f"ALTER TABLE applications ALTER COLUMN {col} TYPE TEXT")
                )
