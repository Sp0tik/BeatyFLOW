"""Генерація і повторна серверна валідація слотів.

UI ніколи не є джерелом істини: навіть якщо користувач натиснув стару inline-кнопку,
цей модуль повторно перевіряє активність майстра/послуги, горизонт запису, робочі
інтервали, вихідні та конфлікти.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Booking, BookingStatus, DayOff, Master, MasterService, Service, WorkingHours

TZ = ZoneInfo(settings.timezone)
ACTIVE = (BookingStatus.pending, BookingStatus.confirmed)


async def _assignment(session: AsyncSession, master_id: int, service_id: int) -> MasterService | None:
    return await session.scalar(
        select(MasterService)
        .join(Master, Master.id == MasterService.master_id)
        .join(Service, Service.id == MasterService.service_id)
        .where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
            Master.is_active.is_(True),
            Service.is_active.is_(True),
        )
    )


async def _working_intervals(
    session: AsyncSession, master_id: int, target_date: date
) -> list[tuple[datetime, datetime]]:
    rows = (
        await session.scalars(
            select(WorkingHours)
            .where(
                WorkingHours.master_id == master_id,
                WorkingHours.weekday == target_date.weekday(),
            )
            .order_by(WorkingHours.start_time)
        )
    ).all()
    return [
        (
            datetime.combine(target_date, row.start_time, tzinfo=TZ),
            datetime.combine(target_date, row.end_time, tzinfo=TZ),
        )
        for row in rows
    ]


async def get_free_slots(
    session: AsyncSession,
    master_id: int,
    service_id: int,
    target_date: date,
    *,
    exclude_booking_id: int | None = None,
) -> list[datetime]:
    now = datetime.now(TZ)
    if target_date < now.date() or target_date >= now.date() + timedelta(days=settings.booking_horizon_days):
        return []

    ms = await _assignment(session, master_id, service_id)
    if ms is None:
        return []

    day_off = await session.scalar(
        select(DayOff.id).where(DayOff.master_id == master_id, DayOff.date == target_date)
    )
    if day_off is not None:
        return []

    intervals = await _working_intervals(session, master_id, target_date)
    if not intervals:
        return []

    duration = timedelta(minutes=ms.duration_min)
    buffer_after = timedelta(minutes=int(ms.buffer_min or settings.default_buffer_minutes))
    day_start = min(x[0] for x in intervals)
    day_end = max(x[1] for x in intervals)

    stmt = select(Booking).where(
        Booking.master_id == master_id,
        Booking.status.in_(ACTIVE),
        Booking.start_at < day_end,
        Booking.end_at > day_start,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    existing = (await session.scalars(stmt)).all()
    busy_ranges = [(b.start_at, b.end_at) for b in existing]

    step = timedelta(minutes=settings.slot_step_minutes)
    slots: list[datetime] = []
    for interval_start, interval_end in intervals:
        cursor = interval_start
        while cursor + duration + buffer_after <= interval_end:
            service_end = cursor + duration
            blocked_end = service_end + buffer_after
            if cursor >= now:
                overlaps = any(cursor < b_end and blocked_end > b_start for b_start, b_end in busy_ranges)
                if not overlaps:
                    slots.append(cursor)
            cursor += step
    return slots


async def is_slot_valid(
    session: AsyncSession,
    master_id: int,
    service_id: int,
    start_at: datetime,
    *,
    exclude_booking_id: int | None = None,
) -> bool:
    """Повторна перевірка конкретного часу без довіри до callback_data."""
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=TZ)
    else:
        start_at = start_at.astimezone(TZ)
    slots = await get_free_slots(
        session,
        master_id,
        service_id,
        start_at.date(),
        exclude_booking_id=exclude_booking_id,
    )
    # Секунди/мікросекунди callback-даних не повинні дозволяти обійти сітку слотів.
    normalized = start_at.replace(second=0, microsecond=0)
    return any(s.replace(second=0, microsecond=0) == normalized for s in slots)
