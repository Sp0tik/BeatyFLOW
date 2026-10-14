"""Надсилання періодичних розсилок клієнтам.

Модель (за погодженням з власником): повідомлення надсилається кожному клієнту
кожні `Broadcast.interval_days` днів, відлік — від максимальної з цих дат:
  · останнього не скасованого візиту клієнта (максимум start_at завершених/майбутніх
    записів зі статусом, що не є cancelled_*), або
  · дати реєстрації клієнта в боті, якщо візитів ще не було;
  · не пізніше останнього фактичного надсилання цієї розсилки цьому клієнту.

Тобто перше повідомлення — за N днів після візиту, повтори — кожні N днів,
а новий візит зсуває лічильник на N днів уперед.

Одержувачі: усі клієнти з clients, окрім майстрів (masters.tg_id) і власника.
"""
import asyncio
from datetime import datetime, timedelta
from html import escape as html_escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Broadcast, BroadcastSend, Booking, BookingStatus, Client, Master
from app.utils.db_text import decode_entities

TZ = ZoneInfo(settings.timezone)

# Затримка між повідомленнями, щоб не вилетіти в flood-control Telegram.
SEND_DELAY_SECONDS = 0.05


async def broadcast_recipients(session: AsyncSession) -> list[Client]:
    """Клієнти-одержувачі: усі, окрім майстрів і власника панелі."""
    master_tg_ids = set(
        (await session.scalars(select(Master.tg_id).where(Master.tg_id.is_not(None)))).all()
    )
    excluded = set(master_tg_ids)
    if settings.owner_tg_id:
        excluded.add(settings.owner_tg_id)

    clients = (await session.scalars(select(Client).where(Client.tg_id.is_not(None), Client.marketing_opt_in.is_(True)))).all()
    return [c for c in clients if c.tg_id not in excluded]


async def _schedule_anchor(session: AsyncSession) -> dict[int, datetime]:
    """client_id -> момент останнього не скасованого візиту (якщо був)."""
    rows = await session.execute(
        select(Booking.client_id, func.max(Booking.start_at))
        .where(
            Booking.status.notin_(
                [BookingStatus.cancelled_client, BookingStatus.cancelled_master]
            )
        )
        .group_by(Booking.client_id)
    )
    return {client_id: moment for client_id, moment in rows.all()}


async def due_clients(session: AsyncSession, broadcast: Broadcast) -> list[Client]:
    """Клієнти, яким час надіслати цю розсилку зараз."""
    now = datetime.now(TZ)
    recipients = await broadcast_recipients(session)
    if not recipients:
        return []

    visits = await _schedule_anchor(session)
    last_sends = {
        client_id: moment
        for client_id, moment in (
            await session.execute(
                select(BroadcastSend.client_id, func.max(BroadcastSend.sent_at))
                .where(BroadcastSend.broadcast_id == broadcast.id)
                .group_by(BroadcastSend.client_id)
            )
        ).all()
    }

    due: list[Client] = []
    interval = timedelta(days=broadcast.interval_days)
    for client in recipients:
        base = visits.get(client.id) or client.created_at
        last_send = last_sends.get(client.id)
        if last_send is not None and last_send > base:
            base = last_send
        if now >= base + interval:
            due.append(client)
    return due


async def deliver(
    bot: Bot, session: AsyncSession, broadcast: Broadcast, clients: list[Client]
) -> tuple[int, int]:
    """Надсилає розсилку та зберігає окремо успіх/невдачу для статистики."""
    now = datetime.now(TZ)
    ok = failed = 0
    for client in clients:
        success = False
        error_code: str | None = None
        try:
            try:
                await bot.send_message(client.tg_id, broadcast.text)
            except TelegramBadRequest:
                await bot.send_message(client.tg_id, html_escape(decode_entities(broadcast.text)))
            ok += 1
            success = True
        except TelegramForbiddenError:
            failed += 1
            error_code = "forbidden"
        except TelegramBadRequest:
            failed += 1
            error_code = "bad_request"
        except Exception as exc:
            failed += 1
            error_code = type(exc).__name__[:64]
        session.add(
            BroadcastSend(
                broadcast_id=broadcast.id,
                client_id=client.id,
                sent_at=now,
                success=success,
                error_code=error_code,
            )
        )
        await asyncio.sleep(SEND_DELAY_SECONDS)
    await session.flush()
    return ok, failed
