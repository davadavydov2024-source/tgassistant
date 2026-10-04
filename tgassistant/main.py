import asyncio
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import config, db, menu, business
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
    dp.include_router(menu.router)
    dp.include_router(business.router)
    asyncio.create_task(profile.time_loop(bot))
    asyncio.create_task(utils.remind_loop(bot))
    me = await bot.me()
    logging.info("Бот @%s запущен", me.username)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
