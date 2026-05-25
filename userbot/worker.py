"""Цикл опроса очереди публикаций и публикация через Telethon.

Запускается отдельным сервисом (``python -m userbot.main``) и работает 24/7.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from db.queries import (
    claim_next_publication,
    count_pending_publications,
    mark_publication_failed,
    mark_publication_published,
    set_application_channel_message,
)
from userbot.publisher import publish_application
from userbot.settings import UserbotSettings

logger = logging.getLogger(__name__)


def build_session_factory(settings: UserbotSettings) -> async_sessionmaker:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=2,
        max_overflow=2,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def build_client(settings: UserbotSettings) -> TelegramClient:
    """Создаёт TelegramClient с StringSession (хранится в env, persistent)."""
    return TelegramClient(
        StringSession(settings.session_string),
        settings.api_id,
        settings.api_hash,
        # параметры устойчивости к разрывам сети — Render-машины уходят в idle,
        # надо чтобы клиент сам поднимался обратно.
        connection_retries=None,  # None = бесконечный retry
        retry_delay=5,
        auto_reconnect=True,
        request_retries=5,
        timeout=30,
    )


async def _process_one(
    session_factory: async_sessionmaker,
    client: TelegramClient,
    settings: UserbotSettings,
) -> bool:
    """Берёт одну задачу из очереди и публикует. Возвращает True, если работа была."""
    async with session_factory() as session:
        try:
            pub = await claim_next_publication(session)
            if pub is None:
                await session.commit()
                return False
            pub_id = pub.id
            application_id = pub.application_id
            body_html = pub.body_html
            photos = [p.data for p in pub.photos]
            attempts = pub.attempts
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info("Publishing channel post: pub_id=%s app_id=%s attempt=%s photos=%s",
                pub_id, application_id, attempts, len(photos))

    try:
        channel_message_id = await publish_application(
            client,
            channel_id=settings.channel_id,
            body_html=body_html,
            photos=photos,
            delay_between_texts=settings.publish_delay_between_texts,
            delay_before_photos=settings.publish_delay_before_photos,
        )
    except FloodWaitError as e:
        wait = int(getattr(e, "seconds", 30))
        logger.warning("FloodWait for pub_id=%s: sleep %ss", pub_id, wait)
        async with session_factory() as session:
            await mark_publication_failed(session, pub_id, f"FloodWait {wait}s")
            await session.commit()
        await asyncio.sleep(wait + 1)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to publish pub_id=%s: %s", pub_id, exc)
        permanent = attempts >= 4
        async with session_factory() as session:
            await mark_publication_failed(session, pub_id, repr(exc), permanent=permanent)
            await session.commit()
        return True

    async with session_factory() as session:
        await mark_publication_published(session, pub_id, channel_message_id)
        if channel_message_id is not None:
            await set_application_channel_message(session, application_id, channel_message_id)
        await session.commit()
    logger.info("Published pub_id=%s channel_message_id=%s", pub_id, channel_message_id)
    return True


async def run_worker(settings: UserbotSettings) -> None:
    """Главный цикл: подключаемся к Telegram, опрашиваем очередь, публикуем."""
    session_factory = build_session_factory(settings)
    client = build_client(settings)

    logger.info("Connecting to Telegram as userbot ...")
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "TELEGRAM_SESSION недействителен. Сгенерируйте новую сессию через "
            "scripts/generate_session.py и обновите переменную окружения."
        )
    me = await client.get_me()
    logger.info("Userbot logged in as id=%s username=@%s name=%s",
                me.id, me.username, me.first_name)

    try:
        while True:
            try:
                worked = await _process_one(session_factory, client, settings)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Worker loop iteration failed; continuing")
                worked = False

            if not worked:
                # Очередь пуста — ждём. Заодно периодически логируем глубину очереди
                # для диагностики.
                try:
                    async with session_factory() as session:
                        pending = await count_pending_publications(session)
                        await session.commit()
                    if pending:
                        logger.debug("Queue depth: %s", pending)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to read queue depth")
                await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await client.disconnect()
        logger.info("Userbot disconnected")
