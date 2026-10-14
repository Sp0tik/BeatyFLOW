"""Панель власника — аналітика за поточний місяць.

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

from datetime import datetime, timedelta
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.owner.common import TZ, _is_owner
from app.keyboards import OWNER_ANALYTICS_BTN
from app.models import Booking, BookingStatus, Master, Service

router = Router(name="owner_analytics")


# ──────────────────────────── аналітика / CRM клієнтів ────────────────────────────

@router.message(F.text == OWNER_ANALYTICS_BTN)
async def owner_analytics(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    await state.clear()
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    total = (await session.scalar(select(func.count(Booking.id)).where(Booking.start_at >= month_start, Booking.start_at < next_month))) or 0
    completed = (await session.scalar(select(func.count(Booking.id)).where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status == BookingStatus.completed))) or 0
    no_show = (await session.scalar(select(func.count(Booking.id)).where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status == BookingStatus.no_show))) or 0
    cancelled = (await session.scalar(select(func.count(Booking.id)).where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status.in_([BookingStatus.cancelled_client, BookingStatus.cancelled_master])))) or 0
    revenue = (await session.scalar(select(func.coalesce(func.sum(Booking.price_snapshot), 0)).where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status == BookingStatus.completed))) or 0

    top_service_row = (await session.execute(
        select(Service.name, func.count(Booking.id).label("cnt"))
        .join(Booking, Booking.service_id == Service.id)
        .where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status.notin_([BookingStatus.cancelled_client, BookingStatus.cancelled_master]))
        .group_by(Service.id, Service.name).order_by(func.count(Booking.id).desc()).limit(1)
    )).first()
    top_master_row = (await session.execute(
        select(Master.full_name, func.count(Booking.id).label("cnt"))
        .join(Booking, Booking.master_id == Master.id)
        .where(Booking.start_at >= month_start, Booking.start_at < next_month, Booking.status.notin_([BookingStatus.cancelled_client, BookingStatus.cancelled_master]))
        .group_by(Master.id, Master.full_name).order_by(func.count(Booking.id).desc()).limit(1)
    )).first()

    service_text = f"{top_service_row[0]} ({top_service_row[1]})" if top_service_row else "—"
    master_text = f"{top_master_row[0]} ({top_master_row[1]})" if top_master_row else "—"
    await message.answer(
        f"📊 <b>Аналітика за {month_start.strftime('%m.%Y')}</b>\n\n"
        f"📅 Усього записів: <b>{total}</b>\n"
        f"✅ Завершено: <b>{completed}</b>\n"
        f"🚫 No-show: <b>{no_show}</b>\n"
        f"❌ Скасовано: <b>{cancelled}</b>\n"
        f"💰 Фактична виручка завершених: <b>{float(revenue):.0f}₴</b>\n\n"
        f"💅 Найпопулярніша послуга: {html_escape(service_text)}\n"
        f"💇‍♀️ Найзавантаженіший майстер: {html_escape(master_text)}"
    )
