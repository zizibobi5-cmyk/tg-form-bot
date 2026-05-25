"""Однократно генерирует TELEGRAM_SESSION (StringSession) для юзербота.

Запускать ЛОКАЛЬНО на вашей машине (не на Render!):

    export TELEGRAM_API_ID=...
    export TELEGRAM_API_HASH=...
    python scripts/generate_session.py

Скрипт интерактивно спросит номер телефона, код из Telegram и (если настроена)
двухфакторную защиту. На выходе выдаст одну длинную строку — это и есть
``TELEGRAM_SESSION``. Скопируйте её в переменные окружения Render для нового
сервиса юзербота.

ВНИМАНИЕ: эта строка даёт ПОЛНЫЙ доступ к вашему Telegram-аккаунту от лица
юзербота. Не публикуйте её, не коммитьте в репозиторий.
"""
from __future__ import annotations

import asyncio
import os
import sys

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("Установите telethon: pip install telethon", file=sys.stderr)
    raise


async def main() -> None:
    api_id_raw = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id_raw or not api_hash:
        print("Сначала задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в окружении.")
        print("Их можно получить на https://my.telegram.org → API development tools.")
        sys.exit(2)
    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("TELEGRAM_API_ID должен быть числом", file=sys.stderr)
        sys.exit(2)

    print("\nСейчас откроется логин в Telegram.")
    print("Вы можете использовать свой основной аккаунт с Telegram Premium —")
    print("или, безопаснее, создать отдельный Premium-аккаунт специально для бота.\n")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()  # интерактивно спросит phone + code + (опционально) password
    me = await client.get_me()
    session_str = client.session.save()
    await client.disconnect()

    print("\n=================== TELEGRAM_SESSION ===================")
    print(session_str)
    print("========================================================")
    print(f"\nЛогин: id={me.id}, username=@{me.username}, имя={me.first_name}")
    if not getattr(me, "premium", False):
        print(
            "\nВНИМАНИЕ: у этого аккаунта НЕТ Telegram Premium. "
            "Премиум-эмодзи всё равно будут резаться при публикации. "
            "Активируйте Premium на этом аккаунте."
        )
    print("\nСкопируйте строку выше в переменную окружения TELEGRAM_SESSION на Render.")


if __name__ == "__main__":
    asyncio.run(main())
