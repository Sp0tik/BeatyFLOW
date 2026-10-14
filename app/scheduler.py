from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from zoneinfo import ZoneInfo

from app.config import settings
from app.database import async_session
from app.models import Booking, BookingStatus, Broadcast
from app.services.broadcast import deliver, due_clients
from app.utils.dates import format_moment

TZ = ZoneInfo(settings.timezone)


async def send_reminders(bot: Bot) -> None:
    """Надсилає всі вже-дозрілі нагадування, а не тільки вузьке ±2 хв вікно.

    Тому рестарт/простій scheduler не губить нагадування: якщо до запису лишилось
    менше reminder_hours_before і запис ще не почався, він буде підібраний.
    """
    now = datetime.now(TZ)
    due_before = now + timedelta(hours=settings.reminder_hours_before)

    async with async_session() as session:
        bookings = (
            await session.scalars(
                select(Booking)
                .where(
                    Booking.status == BookingStatus.confirmed,
                    Booking.reminder_sent.is_(False),
                    Booking.start_at > now,
                    Booking.start_at <= due_before,
                )
                .order_by(Booking.start_at)
            )
        ).all()

        for booking in bookings:
            client = booking.client
            mark_done = False
            try:
                await bot.send_message(
                    client.tg_id,
                    f"⏰ Нагадування: у вас запис {format_moment(booking.start_at)}. Чекаємо на вас!",
                )
                mark_done = True
            except (TelegramForbiddenError, TelegramBadRequest):
                # Постійна помилка (бот заблокований / чат недоступний): не спамимо ретраями.
                mark_done = True
            except Exception:
                # Тимчасову мережеву помилку спробуємо ще раз на наступному циклі.
                mark_done = False
            if mark_done:
                booking.reminder_sent = True

        await session.commit()


async def send_broadcasts(bot: Bot) -> None:
    now = datetime.now(TZ)
    if not (settings.broadcast_hour_start <= now.hour < settings.broadcast_hour_end):
        return

    async with async_session() as session:
        broadcasts = (
            await session.scalars(select(Broadcast).where(Broadcast.is_active.is_(True)))
        ).all()
        for broadcast in broadcasts:
            clients = await due_clients(session, broadcast)
            if clients:
                await deliver(bot, session, broadcast, clients)
        await session.commit()


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=str(TZ))
    scheduler.add_job(
        send_reminders,
        "interval",
        minutes=5,
        args=[bot],
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        send_broadcasts,
        "interval",
        minutes=30,
        args=[bot],
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler
