import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

import database as db
from admin_handlers import router as admin_router
from config import (
    AUTO_ARCHIVE_ENABLED,
    AUTO_ARCHIVE_INTERVAL_SECONDS,
    BOT_TOKEN,
    DATABASE_PATH,
    DATA_DIR,
    LOG_DIR,
    LOG_LEVEL,
)
from middleware import AntiFloodMiddleware
from user_handlers import router as user_router


logger = logging.getLogger(__name__)
errors_router = Router()


def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = RotatingFileHandler(LOG_DIR / 'job_bot.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


@errors_router.errors()
async def on_error(event: ErrorEvent):
    logger.exception('Unhandled update error', exc_info=event.exception)
    try:
        if event.update.message:
            await event.update.message.answer('⚠️ Что-то пошло не так. Попробуй ещё раз.')
        elif event.update.callback_query:
            await event.update.callback_query.answer('Ошибка. Попробуй ещё раз.', show_alert=True)
    except Exception:
        logger.exception('Failed to send fallback error message')
    return True


async def auto_archive_worker(bot: Bot):
    while True:
        try:
            archived = db.archive_expired_tasks()
            if archived:
                logger.info('Auto-archived tasks: %s', archived)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Auto archive worker failed')
        await asyncio.sleep(max(60, AUTO_ARCHIVE_INTERVAL_SECONDS))


async def main():
    setup_logging()
    if not BOT_TOKEN:
        raise RuntimeError('Укажи BOT_TOKEN в .env')

    os.makedirs(os.path.dirname(DATABASE_PATH) or '.', exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    db.init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    antiflood = AntiFloodMiddleware()
    dp.message.middleware(antiflood)
    dp.callback_query.middleware(antiflood)

    dp.include_router(errors_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    bg_task = None
    if AUTO_ARCHIVE_ENABLED:
        bg_task = asyncio.create_task(auto_archive_worker(bot))

    try:
        logger.info('Job bot v4 started')
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if bg_task:
            bg_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bg_task


if __name__ == '__main__':
    import contextlib

    asyncio.run(main())
