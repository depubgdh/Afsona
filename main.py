"""Ishga tushirish: bot (polling) + veb-server bitta jarayonda."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

import backup
import bot as bot_mod
import config
import db
import server


async def main():
    logging.basicConfig(level=logging.INFO)
    if not config.BOT_TOKEN or not config.WEBAPP_URL:
        raise SystemExit("BOT_TOKEN va WEBAPP_URL ni sozlang (.env.example ga qarang)")
    session = None
    if config.BOT_API_URL:                                   # o'z Bot API serveri bo'lsa
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.BOT_API_URL, is_local=True))
    bot = Bot(config.BOT_TOKEN, session=session)
    await backup.restore_if_empty()                          # deploydan keyin baza bo'sh bo'lsa — zaxiradan tiklaymiz
    db.init_db()
    if not config.BOT_USERNAME:
        config.BOT_USERNAME = (await bot.get_me()).username
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎬 Kinolar", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    except Exception:
        pass
    asyncio.create_task(backup.loop())
    runner = web.AppRunner(server.make_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    dp = Dispatcher()
    dp.include_router(bot_mod.router)
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
