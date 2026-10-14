"""Панель власника — майстри: список, додавання, картка, записи, видалення.

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

import secrets
from datetime import datetime
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import TEXT_INPUT
from app.handlers.owner.common import OwnerFlow, TZ, _is_owner, _safe_edit
from app.keyboards import (
    OWNER_MANAGE_BTN,
    owner_cancel_kb,
    owner_master_bookings_kb,
    owner_master_delete_confirm_kb,
    owner_master_detail_kb,
    owner_masters_list_kb,
    yes_no_kb,
)
from app.models import Booking, BookingStatus, DayOff, Master, MasterService, WorkingHours
from app.utils.dates import format_moment
from app.utils.db_text import storable_problem

router = Router(name="owner_masters")


# ──────────────────────────── список майстрів ────────────────────────────


async def _render_masters_list(message: Message, session: AsyncSession, edit: bool) -> None:
    masters = (await session.scalars(select(Master).order_by(Master.id))).all()
    items = [(m.id, m.full_name, m.is_active) for m in masters]

    text = "Майстри салону:" if items else "Майстрів ще немає — додайте першого 👇"
    kb = owner_masters_list_kb(items)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.message(F.text == OWNER_MANAGE_BTN)
async def owner_manage(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    await state.clear()  # вихід із кроків введення ціни/імені тощо
    await _render_masters_list(message, session, edit=False)


@router.callback_query(F.data == "ownerback")
async def owner_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await _render_masters_list(callback.message, session, edit=True)
    await callback.answer()


# ──────────────────────────── додати майстра ────────────────────────────


@router.callback_query(F.data == "owneraddmaster")
async def owner_add_master_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_text(
        "Введіть ім'я нового майстра (як показувати клієнтам):",
        reply_markup=owner_cancel_kb("ownerback"),
    )
    await state.set_state(OwnerFlow.entering_master_name)
    await callback.answer()


@router.message(OwnerFlow.entering_master_name, TEXT_INPUT)
async def owner_add_master_finish(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return

    name = message.text.strip()
    if not name:
        await message.answer("Ім'я не може бути порожнім, спробуйте ще раз:")
        return

    problem = await storable_problem(session, name)
    if problem:
        await message.answer(problem)
        return

    auth_code = secrets.token_urlsafe(16)
    master = Master(full_name=name, auth_code=auth_code, is_active=True)
    session.add(master)
    await session.commit()
    await state.clear()

    # Послуги НЕ підключаються автоматично — власник сам добирає потрібні
    # (індивідуальні ціни/тривалість) через «🧾 Послуги та ціни майстра».
    text = f"✅ Майстра «{name}» додано!\n\nКод авторизації: <code>{auth_code}</code>\n"
    text += f"Передайте його майстру — він має написати боту:\n<code>/master {auth_code}</code>"
    text += (
        "\n\n🧾 Далі підключіть майстру послуги: відкрийте майстра → "
        "«Послуги та ціни майстра» → «Додати послугу»."
    )

    await message.answer(text)
    await _render_masters_list(message, session, edit=False)


# ──────────────────────────── деталі майстра ────────────────────────────


@router.callback_query(F.data.startswith("ownermaster:"))
async def owner_master_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    status = "активний 🟢" if master.is_active else "деактивований ⚪️"
    auth_line = (
        f"Код авторизації: <code>{master.auth_code}</code>"
        if master.auth_code
        else "Код авторизації відсутній"
    )
    linked_line = "Прив'язаний Telegram-акаунт: є ✅" if master.tg_id else "Ще не авторизувався в боті ⏳"

    await callback.message.edit_text(
        f"<b>{master.full_name}</b>\nСтатус: {status}\n{linked_line}\n{auth_line}",
        reply_markup=owner_master_detail_kb(master.id, master.is_active),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownermtoggle:"))
async def owner_toggle_master(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return
    if master.is_active:
        active = await _future_active_bookings_count(session, master_id)
        if active:
            await callback.answer(
                f"Спочатку скасуйте або перенесіть {active} майбутніх запис(ів).",
                show_alert=True,
            )
            return
        master.is_active = False
        master.tg_id = None
        master.auth_code = None
    else:
        master.is_active = True
        master.auth_code = secrets.token_urlsafe(16)
    await session.commit()
    await callback.answer("Статус майстра оновлено")
    await owner_master_detail(callback, session)


@router.callback_query(F.data.startswith("ownerregen:"))
async def owner_regen_code(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    master.auth_code = secrets.token_urlsafe(16)
    master.tg_id = None
    await session.commit()
    await callback.answer("Новий код згенеровано")
    await owner_master_detail(callback, session)


# ──────────────────────────── записи майстра (панель власника) ────────────────────────────


async def _owner_master_bookings_payload(
    session: AsyncSession, master: Master
) -> tuple[str, InlineKeyboardMarkup]:
    """Майбутні активні записи майстра: текст + кнопки для скасування.

    Власник бачить, коли в майстра є клієнти, і може скасувати конкретний запис —
    клієнт про це отримає повідомлення (так само, як при скасуванні майстром).
    """
    bookings = list(
        (
            await session.scalars(
                select(Booking)
                .where(
                    Booking.master_id == master.id,
                    Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
                    Booking.start_at >= datetime.now(TZ),
                )
                .order_by(Booking.start_at)
                .limit(30)
            )
        ).all()
    )

    header = f"<b>{html_escape(master.full_name)}</b> — майбутні записи:"
    if not bookings:
        return f"{header}\n\nЗаписів немає 🙂", owner_master_bookings_kb(master.id, [])

    lines = []
    items = []
    for b in bookings:
        cname = b.client.full_name if b.client else "?"
        cphone = b.client.phone if b.client and b.client.phone else None
        sname = b.service.name if b.service else "?"
        tail = f" · 📞 {cphone}" if cphone else ""
        lines.append(
            f"🕐 {format_moment(b.start_at)} — {html_escape(cname)} ({html_escape(sname)}){tail}"
        )
        items.append((b.id, f"🕐 {format_moment(b.start_at)} · {cname}"))

    text = header + "\n" + "\n".join(lines) + "\n\nЩоб скасувати запис — тапніть на нього 👇"
    return text, owner_master_bookings_kb(master.id, items)


@router.callback_query(F.data.startswith("ownermbook:"))
async def owner_master_bookings(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    text, kb = await _owner_master_bookings_payload(session, master)
    await _safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ownermbookpick:"))
async def owner_master_booking_pick(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, master_raw, booking_raw = callback.data.split(":")
    booking = await session.get(Booking, int(booking_raw))
    # запис мусить належати тому майстру, з картки якого прийшов тап
    if booking is None or booking.master_id != int(master_raw):
        await callback.answer("Запис не знайдено.", show_alert=True)
        return

    client = booking.client
    cname = client.full_name if client else "?"
    cphone = client.phone if client and client.phone else None
    pline = f"\n📞 {cphone}" if cphone else ""
    sname = booking.service.name if booking.service else "?"

    await _safe_edit(
        callback.message,
        f"Скасувати запис <b>{html_escape(cname)}</b> на {format_moment(booking.start_at)}"
        f" ({html_escape(sname)})?{pline}\n\nКлієнт отримає повідомлення про скасування.",
        yes_no_kb(f"ownermbookcancelyes:{master_raw}:{booking_raw}", f"ownermbook:{master_raw}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownermbookcancelyes:"))
async def owner_master_booking_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, master_raw, booking_raw = callback.data.split(":")
    booking = await session.get(Booking, int(booking_raw))
    if booking is None or booking.master_id != int(master_raw):
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    if booking.status not in (BookingStatus.confirmed, BookingStatus.pending):
        await callback.answer("Цей запис уже не активний.", show_alert=True)
        return

    moment = format_moment(booking.start_at)
    client = booking.client
    client_tg_id = client.tg_id if client else None

    booking.status = BookingStatus.cancelled_master
    await session.commit()

    master = await session.get(Master, booking.master_id)
    if master is None:
        text, kb = f"✅ Запис на {moment} скасовано.", owner_master_bookings_kb(int(master_raw), [])
    else:
        text, kb = await _owner_master_bookings_payload(session, master)
        text = f"✅ Запис на {moment} скасовано.\n\n{text}"
    await _safe_edit(callback.message, text, kb)
    await callback.answer("Запис скасовано")

    if client_tg_id:
        try:
            await callback.bot.send_message(
                client_tg_id,
                f"😔 Ваш запис на {moment} скасовано.\n"
                f"Будь ласка, оберіть новий час — натисніть «📅 Записатися».",
            )
        except Exception:
            pass


# ──────────────────────────── видалення майстра ────────────────────────────


async def _future_active_bookings_count(session: AsyncSession, master_id: int) -> int:
    """Майбутні записи pending/confirmed — поки є, майстра видаляти не можна."""
    now = datetime.now(TZ)
    return (
        await session.scalar(
            select(func.count(Booking.id)).where(
                Booking.master_id == master_id,
                Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed]),
                Booking.start_at >= now,
            )
        )
    ) or 0


@router.callback_query(F.data.startswith("ownerdelmaster:"))
async def owner_master_delete_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Екран підтвердження: 'ownerdelmaster:<master_id>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    active = await _future_active_bookings_count(session, master_id)
    if active:
        await callback.answer(
            f"⛔ У майстра {active} активних майбутніх запис(ів) — спочатку їх скасуйте.",
            show_alert=True,
        )
        return

    await state.clear()
    await callback.message.edit_text(
        f"⚠️ Видалити майстра «{master.full_name}»?\n\n"
        "Буде видалено назавжди разом з його вихідними, робочими годинами, "
        "індивідуальними цінами та усією історією записів. "
        "Дію неможливо скасувати.",
        reply_markup=owner_master_delete_confirm_kb(master_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownerdelmasteryes:"))
async def owner_master_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Hard delete: 'ownerdelmasteryes:<master_id>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    # Повторна перевірка — між екраном підтвердження і натисканням міг з'явитися запис.
    active = await _future_active_bookings_count(session, master_id)
    if active:
        await callback.answer(
            f"⛔ З'явились активні записи ({active}) — видалення скасовано.",
            show_alert=True,
        )
        return

    # Каскад у БД має прибрати child-рядки, але видаляємо явно — сесія бачить
    # їх через relationships і ORM-видалення майстра може спробувати їх оновити.
    await session.execute(sa_delete(Booking).where(Booking.master_id == master_id))
    await session.execute(sa_delete(DayOff).where(DayOff.master_id == master_id))
    await session.execute(sa_delete(WorkingHours).where(WorkingHours.master_id == master_id))
    await session.execute(sa_delete(MasterService).where(MasterService.master_id == master_id))
    await session.execute(sa_delete(Master).where(Master.id == master_id))
    await session.commit()

    await callback.answer(f"✅ Майстра «{master.full_name}» видалено")
    await _render_masters_list(callback.message, session, edit=True)
