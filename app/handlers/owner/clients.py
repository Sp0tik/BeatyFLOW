"""Панель власника — CRM: список клієнтів і картка клієнта.

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.owner.common import _is_owner
from app.keyboards import OWNER_CLIENTS_BTN, owner_clients_list_kb
from app.models import Booking, BookingStatus, Client
from app.utils.dates import format_moment

router = Router(name="owner_clients")


@router.message(F.text == OWNER_CLIENTS_BTN)
async def owner_clients(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    await state.clear()
    clients = (await session.scalars(select(Client).order_by(Client.created_at.desc()).limit(50))).all()
    items = [(c.id, f"👤 {c.full_name}" + (f" · {c.phone}" if c.phone else "")) for c in clients]
    await message.answer(
        "👥 <b>Клієнти</b>\nОстанні 50 клієнтів — натисніть, щоб відкрити картку:",
        reply_markup=owner_clients_list_kb(items),
    )


@router.callback_query(F.data.startswith("ownerclient:"))
async def owner_client_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    client_id = int(callback.data.split(":")[1])
    client = await session.get(Client, client_id)
    if client is None:
        await callback.answer("Клієнта не знайдено.", show_alert=True)
        return
    total = (await session.scalar(select(func.count(Booking.id)).where(Booking.client_id == client.id))) or 0
    completed = (await session.scalar(select(func.count(Booking.id)).where(Booking.client_id == client.id, Booking.status == BookingStatus.completed))) or 0
    no_show = (await session.scalar(select(func.count(Booking.id)).where(Booking.client_id == client.id, Booking.status == BookingStatus.no_show))) or 0
    cancelled = (await session.scalar(select(func.count(Booking.id)).where(Booking.client_id == client.id, Booking.status.in_([BookingStatus.cancelled_client, BookingStatus.cancelled_master])))) or 0
    spent = (await session.scalar(select(func.coalesce(func.sum(Booking.price_snapshot), 0)).where(Booking.client_id == client.id, Booking.status == BookingStatus.completed))) or 0
    last = await session.scalar(select(Booking).where(Booking.client_id == client.id).order_by(Booking.start_at.desc()).limit(1))
    last_text = format_moment(last.start_at) if last else "—"
    marketing = "так ✅" if client.marketing_opt_in else "ні 🔕"
    await callback.message.edit_text(
        f"👤 <b>{html_escape(client.full_name)}</b>\n"
        f"📞 {html_escape(client.phone or '—')}\n"
        f"📅 Записів: {total} · завершено: {completed}\n"
        f"❌ Скасувань: {cancelled} · 🚫 no-show: {no_show}\n"
        f"💰 Витрачено: {float(spent):.0f}₴\n"
        f"🕓 Останній запис: {last_text}\n"
        f"📢 Маркетинг: {marketing}"
    )
    await callback.answer()
