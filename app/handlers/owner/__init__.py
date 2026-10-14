"""Панель власника (пакет).

Монолітний `owner.py` розбито на тематичні модулі; кожен реєструє свої
хендлери на власному `Router`, а цей `__init__` збирає їх в один роутер у
тому ж порядку, у якому вони були в оригінальному файлі. Для `bot.py`
публічна точка входу не змінюється — усе той самий `owner.router`.
"""

from aiogram import Router

from app.handlers.owner import (
    analytics,
    broadcasts,
    clients,
    masters,
    schedule,
    services,
)

router = Router(name="owner")
router.include_router(masters.router)
router.include_router(schedule.router)
router.include_router(services.router)
router.include_router(analytics.router)
router.include_router(clients.router)
router.include_router(broadcasts.router)

__all__ = ["router"]
