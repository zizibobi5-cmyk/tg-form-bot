"""Логика публикации одной анкеты от лица юзербота (Telethon).

Делает то же, что бот делал через ``send_application_messages``:
1. Шлёт текст анкеты, разбивая на несколько сообщений, если превышен лимит 4096 символов.
2. Ждёт ``delay_before_photos`` секунд (Telegram не любит флуд при длинных анкетах).
3. Шлёт фотоальбом (или одно фото) с пустой подписью.

Главное отличие от бота: текст идёт через ``client.send_message(...,
formatting_entities=...)`` с предварительно сконвертированными в Telethon-entities
``<tg-emoji>``. Это и сохраняет премиум-эмодзи в канале.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from telethon import TelegramClient
from telethon.tl.types import TypeInputFile

from userbot.html_to_entities import html_to_text_and_entities

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
MAX_MESSAGES_PER_APPLICATION = 7


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _split_text_and_entities(
    text: str, entities: list[Any], *, limit: int = TELEGRAM_MESSAGE_LIMIT, max_parts: int = MAX_MESSAGES_PER_APPLICATION
) -> list[tuple[str, list[Any]]]:
    """Делит длинный текст на куски с пересчётом offset'ов entities.

    Длина считается в UTF-16 code units (как у Telegram). Сначала ищем
    границу по ``\\n\\n``, потом по ``\\n``, в крайнем случае режем жёстко.
    """
    if _utf16_len(text) <= limit:
        return [(text, list(entities))]

    parts: list[tuple[str, list[Any]]] = []
    remaining = text
    # offset текущего "remaining" относительно исходного текста, в UTF-16 units
    base_offset = 0

    while remaining:
        if _utf16_len(remaining) <= limit:
            parts.append((remaining, _shift_entities(entities, base_offset, _utf16_len(remaining))))
            break
        # Ищем границу: рассчитываем посимвольный индекс в char'ах, который
        # соответствует ``limit`` UTF-16 units. Для большинства символов это
        # 1:1, но для surrogate-пар (эмодзи) — нет.
        # Простой путь: режем по char-индексу, обеспечивая, что UTF-16 длина не
        # превышает limit.
        # Бинарный поиск максимального char-индекса cut такого, что
        # _utf16_len(remaining[:cut]) <= limit.
        lo, hi = 0, len(remaining)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _utf16_len(remaining[:mid]) <= limit:
                lo = mid
            else:
                hi = mid - 1
        max_cut = lo  # char-индекс
        # Ищем "\n\n" или "\n" в [0, max_cut]
        cut = remaining.rfind("\n\n", 0, max_cut)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_cut)
        if cut <= 0:
            cut = max_cut

        chunk = remaining[:cut].rstrip()
        chunk_u16 = _utf16_len(chunk)
        parts.append((chunk, _shift_entities(entities, base_offset, chunk_u16)))

        # сдвигаем base_offset на UTF-16 длину "съеденной" части (включая \n\n или
        # \n, которые мы сейчас выбросим)
        consumed = remaining[:cut]
        consumed_u16 = _utf16_len(consumed)
        # пропускаем ведущие \n из остатка
        rest = remaining[cut:].lstrip("\n")
        skipped_u16 = consumed_u16 + _utf16_len(remaining[cut : cut + (len(remaining[cut:]) - len(rest))])
        base_offset += skipped_u16
        remaining = rest

        if len(parts) >= max_parts - 1:
            # последний кусок — обрезаем жёстко, если не влезает
            if _utf16_len(remaining) > limit:
                # отрезаем по char-индексу с учётом UTF-16
                lo, hi = 0, len(remaining)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if _utf16_len(remaining[:mid]) <= limit - 1:
                        lo = mid
                    else:
                        hi = mid - 1
                tail = remaining[:lo] + "…"
                parts.append((tail, _shift_entities(entities, base_offset, _utf16_len(tail))))
            else:
                parts.append((remaining, _shift_entities(entities, base_offset, _utf16_len(remaining))))
            break

    return parts


def _shift_entities(entities: list[Any], base_offset: int, max_length: int) -> list[Any]:
    """Возвращает копии entities, сдвинутые на ``base_offset`` UTF-16 units,
    обрезанные границей куска ``max_length`` UTF-16 units.

    Entities, целиком лежащие за пределами куска, отбрасываются. Entities, частично
    попадающие в кусок, обрезаются по его границам.
    """
    out: list[Any] = []
    for e in entities:
        e_off = e.offset
        e_end = e.offset + e.length
        chunk_start = base_offset
        chunk_end = base_offset + max_length
        if e_end <= chunk_start or e_off >= chunk_end:
            continue
        new_off = max(e_off, chunk_start) - chunk_start
        new_end = min(e_end, chunk_end) - chunk_start
        new_len = new_end - new_off
        if new_len <= 0:
            continue
        clone = _clone_entity(e, new_off, new_len)
        out.append(clone)
    return out


def _clone_entity(entity: Any, offset: int, length: int) -> Any:
    """Создаёт копию entity с новыми offset/length, сохраняя type-specific поля."""
    cls = type(entity)
    kwargs: dict[str, Any] = {"offset": offset, "length": length}
    # type-specific поля (url, document_id, user_id, language)
    for attr in ("url", "document_id", "user_id", "language"):
        if hasattr(entity, attr):
            kwargs[attr] = getattr(entity, attr)
    return cls(**kwargs)


async def publish_application(
    client: TelegramClient,
    *,
    channel_id: int,
    body_html: str,
    photos: list[bytes],
    delay_between_texts: float = 0.0,
    delay_before_photos: float = 0.0,
) -> int | None:
    """Публикует анкету в канал. Возвращает message_id первого отправленного сообщения,
    или ``None``, если ничего не было отправлено.
    """
    text, entities = html_to_text_and_entities(body_html)
    parts = _split_text_and_entities(text, entities)

    first_message_id: int | None = None

    for idx, (chunk_text, chunk_entities) in enumerate(parts):
        is_last_text = idx == len(parts) - 1
        msg = await client.send_message(
            entity=channel_id,
            message=chunk_text,
            formatting_entities=chunk_entities or None,
            link_preview=False,
        )
        if first_message_id is None and msg is not None:
            first_message_id = msg.id
        if not is_last_text and delay_between_texts > 0:
            await asyncio.sleep(delay_between_texts)

    if photos:
        if delay_before_photos > 0:
            await asyncio.sleep(delay_before_photos)
        # Загружаем каждое фото отдельно через upload_file, потом единым media-альбомом.
        uploaded: list[TypeInputFile] = []
        for i, blob in enumerate(photos):
            buf = io.BytesIO(blob)
            buf.name = f"photo_{i}.jpg"
            uf = await client.upload_file(buf, file_name=buf.name)
            uploaded.append(uf)
        if len(uploaded) == 1:
            sent = await client.send_file(entity=channel_id, file=uploaded[0])
        else:
            sent = await client.send_file(entity=channel_id, file=uploaded)
        if first_message_id is None:
            if isinstance(sent, list) and sent:
                first_message_id = sent[0].id
            elif hasattr(sent, "id"):
                first_message_id = sent.id

    return first_message_id
