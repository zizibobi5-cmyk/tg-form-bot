"""Точка входа сервиса юзербота.

Запускается на Render как отдельный Web Service (или Background Worker).
Использует ту же базу Neon, что и анкетный бот, но не зависит от его
``BOT_TOKEN`` — у юзербота свои credentials (TELEGRAM_API_ID/HASH/SESSION).

Мини-HTTP сервер ``/`` и ``/health`` нужен, чтобы Render Free Web Service
не уходил в сон (UptimeRobot/cron-job пингует этот endpoint).
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from userbot.settings import UserbotSettings
from userbot.worker import run_worker

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Telethon очень болтливый на DEBUG; на INFO достаточно.
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _start_keepalive(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Userbot keep-alive HTTP server on 0.0.0.0:%s", port)
    return runner


async def main() -> None:
    settings = UserbotSettings.load()
    _setup_logging(settings.log_level)

    # PORT на Render задаётся автоматически; используем его, если есть.
    port = int(os.getenv("PORT", str(settings.http_port)))
    runner = await _start_keepalive(port)

    try:
        await run_worker(settings)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
