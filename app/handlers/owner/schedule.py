"""Панель власника — вихідні та відпустки майстра.

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import TEXT_INPUT
from app.handlers.owner.common import OwnerFlow, TZ, _is_owner
from app.keyboards import (
    owner_cancel_kb,
    owner_dayoff_dates_kb,
    owner_dayoff_list_kb,
    owner_dayoff_menu_kb,
)
from app.models import DayOff, Master
from app.services.booking import mark_day_off, mark_days_off_range
from app.utils.dates import format_date_human, format_moment

router = Router(name="owner_schedule")


# ──────────────────────────── вихідні майстра (панель власника) ────────────────────────────


async def _owner_dayoff_payload(
    session: AsyncSession, master_id: int, header: str | None = None
) -> tuple[str, InlineKeyboardMarkup] | None:
    """Текст і клавіатура екрана вихідних майстра. None — якщо майстра не існує."""
    master = await session.get(Master, master_id)
    if master is None:
        return None

    rows = (
        await session.scalars(
            select(DayOff)
            .where(DayOff.master_id == master_id, DayOff.date >= datetime.now(TZ).date())
            .order_by(DayOff.date)
            .limit(30)
        )
    ).all()

    text = f"{header}\n\n" if header else ""
    text += f"<b>Вихідні майстра «{master.full_name}»</b>\n"
    if rows:
        text += "Майбутні вихідні:\n" + "\n".join(
            f"· {format_date_human(r.date)}" for r in rows
        )
    else:
        text += "Майбутні вихідні не позначені."

    return text, owner_dayoff_menu_kb(master_id, has_days_off=bool(rows))


@router.callback_query(F.data.startswith("ownerdayoff:"))
async def owner_dayoff_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Екран «🗓 Вихідні майстра» з деталей майстра."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()

    master_id = int(callback.data.split(":")[1])
    payload = await _owner_dayoff_payload(session, master_id)
    if payload is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return
    text, kb = payload
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass  # повторний тап: текст і клавіатура не змінилися
    await callback.answer()


@router.callback_query(F.data.startswith("ownerdayoffadd:"))
async def owner_dayoff_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Показати пікер дат для позначення вихідного."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    today = datetime.now(TZ).date()
    try:
        await callback.message.edit_text(
            "На яку дату позначити вихідний?\n"
            "⚠️ Активні записи майстра на цю дату буде скасовано, клієнтів сповіщено.",
            reply_markup=owner_dayoff_dates_kb(master_id, [today + timedelta(days=i) for i in range(30)]),
        )
    except TelegramBadRequest:
        pass  # повторний тап: екран не змінився
    await callback.answer()


@router.callback_query(F.data.startswith("ownerdayoffdate:"))
async def owner_dayoff_date_chosen(callback: CallbackQuery, session: AsyncSession) -> None:
    """Позначити вихідний: 'ownerdayoffdate:<master_id>:<iso>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, mid, iso = callback.data.split(":")
    master_id, target = int(mid), date.fromisoformat(iso)

    affected = await mark_day_off(session, master_id, target)
    await session.commit()

    header = f"✅ Позначено вихідний: {format_date_human(target)}"
    if affected:
        header += f"\n⚠️ Автоматично скасовано {len(affected)} запис(ів), клієнтів сповіщено."
    payload = await _owner_dayoff_payload(session, master_id, header=header)
    if payload is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return
    text, kb = payload
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass  # повторний тап по тій самій даті: текст не змінився
    await callback.answer()

    for booking in affected:
        client = booking.client
        if client and client.tg_id:
            try:
                await callback.bot.send_message(
                    client.tg_id,
                    f"😔 На жаль, ваш запис на {format_moment(booking.start_at)} скасовано — "
                    f"у майстра вихідний.\n"
                    f"Будь ласка, оберіть новий час — натисніть «📅 Записатися».",
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("ownerdayoffvac:"))
async def owner_vacation_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    master_id = int(callback.data.split(":")[1])
    await state.update_data(vacation_master_id=master_id)
    await callback.message.edit_text(
        "Введіть період у форматі <code>10.10.2026..20.10.2026</code>.\n"
        "Активні записи в цьому діапазоні будуть скасовані автоматично.",
        reply_markup=owner_cancel_kb(f"ownerdayoff:{master_id}"),
    )
    await state.set_state(OwnerFlow.entering_vacation_range)
    await callback.answer()


@router.message(OwnerFlow.entering_vacation_range, TEXT_INPUT)
async def owner_vacation_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    data = await state.get_data()
    master_id = data.get("vacation_master_id")
    try:
        a, b = [x.strip() for x in message.text.split("..", 1)]
        start = datetime.strptime(a, "%d.%m.%Y").date()
        end = datetime.strptime(b, "%d.%m.%Y").date()
        if end < start:
            start, end = end, start
        if (end - start).days > 366:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("Не розпізнав період. Приклад: 10.10.2026..20.10.2026")
        return
    affected = await mark_days_off_range(session, master_id, start, end)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Відпустку позначено: {format_date_human(start)} — {format_date_human(end)}. "
        f"Скасовано записів: {len(affected)}."
    )
    for booking in affected:
        if booking.client and booking.client.tg_id:
            try:
                await message.bot.send_message(
                    booking.client.tg_id,
                    f"😔 Ваш запис на {format_moment(booking.start_at)} скасовано — майстер у відпустці. "
                    "Оберіть новий час через «📅 Записатися».",
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("ownerdayoffunmark:"))
async def owner_dayoff_unmark_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список позначених вихідних для скасування."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    payload = await _owner_dayoff_payload(session, master_id)
    if payload is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    rows = (
        await session.scalars(
            select(DayOff)
            .where(DayOff.master_id == master_id, DayOff.date >= datetime.now(TZ).date())
            .order_by(DayOff.date)
            .limit(30)
        )
    ).all()
    if not rows:
        await callback.answer("Немає позначених вихідних.", show_alert=True)
        return

    items = [(r.date.isoformat(), f"🗓 {format_date_human(r.date)}") for r in rows]
    try:
        await callback.message.edit_text(
            "Який вихідний скасувати? (день знову стане робочим)",
            reply_markup=owner_dayoff_list_kb(master_id, items),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ownerdayoffcancel:"))
async def owner_dayoff_unmark_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Скасувати вихідний: 'ownerdayoffcancel:<master_id>:<iso>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, mid, iso = callback.data.split(":")
    master_id, target = int(mid), date.fromisoformat(iso)

    row = await session.scalar(
        select(DayOff).where(DayOff.master_id == master_id, DayOff.date == target)
    )
    if row is None:
        await callback.answer("Цей вихідний уже скасовано.", show_alert=True)
        return
    await session.delete(row)
    await session.commit()

    payload = await _owner_dayoff_payload(
        session,
        master_id,
        header=f"✅ Вихідний {format_date_human(target)} скасовано — день знову робочий.",
    )
    if payload is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return
    text, kb = payload
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await callback.answer()
