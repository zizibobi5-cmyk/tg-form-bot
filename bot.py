"""Точка входа Telegram-бота."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from config import get_settings
from db.base import init_db
from handlers import admin, application, moderation, question, start
from middlewares.album import AlbumMiddleware
from middlewares.antiflood import AntiFloodMiddleware
from middlewares.ban import BanMiddleware
from middlewares.db import DbSessionMiddleware
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # общие middleware — порядок важен: сначала сессия, потом проверка бана,
    # потом антифлуд, последним альбом (только на message).
    db_mw = DbSessionMiddleware()
    ban_mw = BanMiddleware()
    flood_mw = AntiFloodMiddleware()

    dp.message.outer_middleware(db_mw)
    dp.message.outer_middleware(ban_mw)
    dp.message.outer_middleware(flood_mw)
    dp.message.outer_middleware(AlbumMiddleware(latency=0.7))

    dp.callback_query.outer_middleware(DbSessionMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(flood_mw)

    # порядок include важен — более специфичные роутеры раньше
    dp.include_router(start.router)
    dp.include_router(application.router)
    dp.include_router(moderation.router)
    dp.include_router(question.router)
    dp.include_router(admin.router)

    return dp


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _start_keepalive_server(port: int) -> web.AppRunner:
    """Поднимает крошечный HTTP-сервер, чтобы Render Free Web Service не засыпал.

    Любой пинг (UptimeRobot, cron-job.org и т.п.) на ``/`` или ``/health``
    считается активностью и продлевает жизнь сервиса.
    """
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Keep-alive HTTP server listening on 0.0.0.0:%s", port)
    return runner


async def main() -> None:
    setup_logging()
    settings = get_settings()
    logger.info("Bot starting...")
    logger.info(
        "Channel: %s, ModeratorChat: %s, Admins: %s",
        settings.channel_id,
        settings.moderator_chat_id,
        settings.admin_ids,
    )

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    keepalive_runner = await _start_keepalive_server(settings.http_port)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await keepalive_runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
