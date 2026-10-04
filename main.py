import asyncio
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from aiogram.types import ErrorEvent

from app import config, db, menu, business, admin_panel, botcmds, errlog
from app.cmds import profile, utils


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if config.DATA_DIR != ".":
        tmp = os.path.join(config.DATA_DIR, "tmp")
        os.makedirs(tmp, exist_ok=True)
        tempfile.tempdir = tmp  # временные файлы медиа-команд тоже пишем в разрешённую папку
    await db.init(config.DB_PATH)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    async def on_error(event: ErrorEvent):
        logging.error("Ошибка обработчика", exc_info=event.exception)
        await errlog.report(bot, f"{type(event.exception).__name__}: {event.exception}")
        return True

    dp.errors.register(on_error)
    dp.include_router(admin_panel.router)
    dp.include_router(botcmds.router)
    dp.include_router(menu.router)
    dp.include_router(business.router)
    asyncio.create_task(profile.time_loop(bot))
    asyncio.create_task(utils.remind_loop(bot))
    me = await bot.me()
    logging.info("Бот @%s запущен, версия %s", me.username, config.VERSION)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
