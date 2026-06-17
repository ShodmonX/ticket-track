import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.core.config import settings
from bot.handlers.start import router as start_router
from bot.handlers.search import router as search_router
from bot.handlers.tracking import router as tracking_router
from bot.handlers.admin import router as admin_router


bot = Bot(token=settings.BOT_TOKEN)

async def on_startup():
    await bot.send_message(settings.ADMIN_ID, "Bot muvaffaqiyatli ishga tushurildi.")

async def on_shutdown():
    await bot.send_message(settings.ADMIN_ID, "Bot ishdan to'xtadi.")

async def main():
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(search_router)
    dp.include_router(tracking_router)
    
    dp.startup.register(on_startup)

    dp.shutdown.register(on_shutdown)

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    try: 
        await dp.start_polling(bot)
    except:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot ishdan to'xtadi.")
    except Exception as e:
        logging.exception(e)
