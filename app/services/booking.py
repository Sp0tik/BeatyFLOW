from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Booking, BookingStatus, Client, DayOff, MasterService
from app.services.slots import is_slot_valid
from app.utils.db_text import to_storable

TZ = ZoneInfo(settings.timezone)


class SlotTakenError(Exception):
    """Слот уже зайнятий або перестав бути валідним."""


async def mark_day_off(session: AsyncSession, master_id: int, target: date) -> list[Booking]:
    existing = await session.scalar(
        select(DayOff).where(DayOff.master_id == master_id, DayOff.date == target)
    )
    if existing is None:
        session.add(DayOff(master_id=master_id, date=target))

    start = datetime.combine(target, datetime.min.time(), tzinfo=TZ)
    end = start + timedelta(days=1)
    affected = (
        await session.scalars(
            select(Booking).where(
                Booking.master_id == master_id,
                Booking.start_at >= start,
                Booking.start_at < end,
                Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
            )
        )
    ).all()
    for booking in affected:
        booking.status = BookingStatus.cancelled_master
    await session.flush()
    return list(affected)


async def mark_days_off_range(
    session: AsyncSession, master_id: int, start: date, end: date, reason: str | None = "Відпустка"
) -> list[Booking]:
    if end < start:
        start, end = end, start
    affected: list[Booking] = []
    current = start
    while current <= end:
        day_affected = await mark_day_off(session, master_id, current)
        row = await session.scalar(
            select(DayOff).where(DayOff.master_id == master_id, DayOff.date == current)
        )
        if row and reason and not row.reason:
            row.reason = reason
        affected.extend(day_affected)
        current += timedelta(days=1)
    return affected


async def get_or_create_client(session: AsyncSession, tg_id: int, full_name: str) -> Client:
    client = await session.scalar(select(Client).where(Client.tg_id == tg_id))
    if client is None:
        client = Client(tg_id=tg_id, full_name=await to_storable(session, full_name))
        session.add(client)
        await session.flush()
    return client


async def _serialize_master_bookings(session: AsyncSession, master_id: int) -> None:
    """PostgreSQL transaction advisory lock: серіалізує конкурентні бронювання майстра.

    Це доповнює exclusion constraint у БД: lock дає дружню перевірку до INSERT,
    constraint залишається останнім фізичним захистом від race condition.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 7_000_000 + master_id})


async def create_booking(
    session: AsyncSession,
    client_id: int,
    master_id: int,
    service_id: int,
    start_at: datetime,
) -> Booking:
    await _serialize_master_bookings(session, master_id)

    if not await is_slot_valid(session, master_id, service_id, start_at):
        raise SlotTakenError()

    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
        )
    )
    if ms is None:
        raise ValueError("Ця послуга недоступна у цього майстра")

    end_at = start_at + timedelta(minutes=ms.duration_min)
    booking = Booking(
        client_id=client_id,
        master_id=master_id,
        service_id=service_id,
        start_at=start_at,
        end_at=end_at,
        status=BookingStatus.confirmed,
        price_snapshot=ms.price,
    )
    session.add(booking)
    try:
        await session.flush()
    except IntegrityError as exc:
        # PostgreSQL exclusion constraint ex_bookings_master_time_overlap.
        await session.rollback()
        raise SlotTakenError() from exc
    return booking


async def reschedule_booking(session: AsyncSession, booking: Booking, new_start_at: datetime) -> Booking:
    if booking.status not in (BookingStatus.pending, BookingStatus.confirmed):
        raise SlotTakenError()
    await _serialize_master_bookings(session, booking.master_id)
    valid = await is_slot_valid(
        session,
        booking.master_id,
        booking.service_id,
        new_start_at,
        exclude_booking_id=booking.id,
    )
    if not valid:
        raise SlotTakenError()
    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == booking.master_id,
            MasterService.service_id == booking.service_id,
        )
    )
    if ms is None:
        raise SlotTakenError()
    booking.start_at = new_start_at
    booking.end_at = new_start_at + timedelta(minutes=ms.duration_min)
    booking.reminder_sent = False
    booking.price_snapshot = ms.price
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise SlotTakenError() from exc
    return booking


async def cancel_booking(session: AsyncSession, booking: Booking, by: str = "client") -> None:
    booking.status = BookingStatus.cancelled_client if by == "client" else BookingStatus.cancelled_master
    await session.flush()
