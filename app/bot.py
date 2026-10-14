import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent

from app.config import settings
from app.handlers import admin, client, owner
from app.middlewares import DbSessionMiddleware
from app.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))

    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(owner.router)  # найспецифічніші текстові кнопки — першими
    dp.include_router(admin.router)
    dp.include_router(client.router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        """Ловить будь-яку необроблену помилку в хендлерах і сповіщає власника в Telegram,
        щоб дізнатись про збій раніше за клієнта — замість того, щоб чергове оновлення
        просто мовчки впало в лог на сервері, який ніхто не читає щодня."""
        logger.exception("Update processing failed", exc_info=event.exception)

        if settings.owner_tg_id:
            short_trace = "".join(traceback.format_exception(event.exception))[-1500:]
            try:
                await bot.send_message(
                    settings.owner_tg_id,
                    f"🔴 Помилка в боті:\n<code>{short_trace}</code>",
                )
            except Exception:
                pass  # навіть сповіщення про помилку не повинно валити процес
        return True

    scheduler = setup_scheduler(bot)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
