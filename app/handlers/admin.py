from datetime import date, datetime, timedelta
import time as monotonic_time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.config import settings
from app.filters import TEXT_INPUT
from app.keyboards import (
    MASTER_BOOKINGS_BTN,
    MASTER_CANCEL_BTN,
    MASTER_STATUS_BTN,
    MASTER_DAYOFF_BTN,
    MASTER_DAYOFF_MARK_TEXT,
    MASTER_OTHER_DAY_BTN,
    MASTER_TODAY_BTN,
    bookings_list_kb,
    dates_kb,
    dayoff_list_kb,
    master_bookings_menu_kb,
    master_dayoff_menu_kb,
    master_menu_kb,
    master_visit_actions_kb,
    master_upcoming_list_kb,
    owner_hours_cancel_kb,
    yes_no_kb,
)
from app.models import Booking, BookingStatus, DayOff, Master, WorkingHours
from app.services.booking import mark_day_off, mark_days_off_range
from app.utils.dates import WEEKDAY_FULL, format_date_human, format_moment, format_time, to_local
from app.utils.schedule_parse import ScheduleParseError, parse_working_hours_text

router = Router(name="admin")
TZ = ZoneInfo(settings.timezone)

# Простий захист /master від brute-force: максимум 5 невдалих спроб за 10 хв.
_AUTH_ATTEMPTS: dict[int, list[float]] = {}



class MasterFlow(StatesGroup):
    choosing_view_date = State()
    choosing_dayoff_action = State()
    choosing_dayoff_date = State()
    choosing_cancel_date = State()
    choosing_cancel_target = State()
    entering_hours = State()
    entering_vacation_range = State()


def _is_owner(tg_id: int) -> bool:
    return settings.owner_tg_id is not None and tg_id == settings.owner_tg_id


async def _get_master(session: AsyncSession, tg_id: int) -> Master | None:
    return await session.scalar(select(Master).where(Master.tg_id == tg_id, Master.is_active.is_(True)))


# ──────────────────────────── авторизація майстра (єдина команда) ────────────────────────────


@router.message(Command("master"))
async def cmd_master_auth(message: Message, session: AsyncSession) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Формат: /master <код_авторизації>\nКод видає власник салону.")
        return

    now_mono = monotonic_time.monotonic()
    attempts = [t for t in _AUTH_ATTEMPTS.get(message.from_user.id, []) if now_mono - t < 600]
    _AUTH_ATTEMPTS[message.from_user.id] = attempts
    if len(attempts) >= 5:
        await message.answer("Забагато невдалих спроб. Спробуйте пізніше або попросіть власника видати новий код.")
        return

    code = parts[1].strip()
    master = await session.scalar(
        select(Master).where(Master.auth_code == code, Master.is_active.is_(True))
    )
    if master is None:
        attempts.append(now_mono)
        await message.answer("Невірний або неактивний код авторизації 😔")
        return

    master.tg_id = message.from_user.id
    master.auth_code = None  # одноразовий код після успішної прив'язки
    _AUTH_ATTEMPTS.pop(message.from_user.id, None)
    await session.commit()

    await message.answer(
        f"✅ Авторизовано як майстер «{master.full_name}»!\nОберіть дію в меню знизу:",
        reply_markup=master_menu_kb(is_owner=_is_owner(message.from_user.id)),
    )


# ──────────────────── "📋 Записи": сьогодні / інша дата (в одному підменю) ────────────────────


async def _ask_which_bookings(message: Message, state: FSMContext) -> None:
    """Одна кнопка «📋 Записи» -> вибір: сьогодні чи інша дата."""
    await state.set_state(MasterFlow.choosing_view_date)
    await message.answer("Які записи показати?", reply_markup=master_bookings_menu_kb())


@router.message(F.text == MASTER_BOOKINGS_BTN)
async def master_bookings_menu(message: Message, state: FSMContext) -> None:
    await _ask_which_bookings(message, state)


# Старі кнопки (лишились у чатах) ведуть у те саме підменю.
@router.message(F.text.in_({MASTER_TODAY_BTN, MASTER_OTHER_DAY_BTN}))
async def master_bookings_menu_legacy(message: Message, state: FSMContext) -> None:
    await _ask_which_bookings(message, state)


async def _master_bookings_on_date(session: AsyncSession, master_id: int, target: date) -> list[Booking]:
    """Активні записи майстра на конкретний день (межі дня — у таймзоні салону)."""
    start = datetime.combine(target, datetime.min.time(), tzinfo=TZ)
    end = start + timedelta(days=1)
    return list(
        (
            await session.scalars(
                select(Booking)
                .where(
                    Booking.master_id == master_id,
                    Booking.start_at >= start,
                    Booking.start_at < end,
                    Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
                )
                .order_by(Booking.start_at)
            )
        ).all()
    )


async def _render_master_day(
    message: Message, session: AsyncSession, master: Master, target: date, edit: bool = False
) -> None:
    """Записи майстра на день: телефон клiента також."""
    bookings = await _master_bookings_on_date(session, master.id, target)
    is_today = target == datetime.now(TZ).date()

    if bookings:
        lines = []
        for b in bookings:
            cname = b.client.full_name if b.client else "?"
            cphone = b.client.phone if b.client and b.client.phone else None
            sname = b.service.name if b.service else "?"
            tail = f" · 📞 {cphone}" if cphone else " · 📞 —"
            lines.append(f"🕐 {format_time(b.start_at)}–{format_time(b.end_at)} — {cname} ({sname}){tail}")
        header = "Записи на сьогодні:" if is_today else f"Записи на {format_date_human(target)}:"
        text = header + "\n" + "\n".join(lines)
    else:
        text = "Сьогодні записів немає. 🎉" if is_today else f"На {format_date_human(target)} записів немає."

    if edit:
        await message.edit_text(text)
    else:
        await message.answer(text)


@router.callback_query(MasterFlow.choosing_view_date, F.data == "mview:today")
async def master_view_today(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await callback.answer("Ви не майстер.", show_alert=True)
        return
    await _render_master_day(callback.message, session, master, datetime.now(TZ).date())
    await callback.answer()


@router.callback_query(MasterFlow.choosing_view_date, F.data == "mview:pick")
async def master_view_pick(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return
    today = datetime.now(TZ).date()
    await callback.message.edit_text(
        "На яку дату подивитись записи?",
        reply_markup=dates_kb([today + timedelta(days=i) for i in range(30)], show_back=False, callback_prefix="mviewdate"),
    )
    await callback.answer()


@router.callback_query(MasterFlow.choosing_view_date, F.data.startswith("mviewdate:"))
async def master_view_chosen(callback: CallbackQuery, session: AsyncSession) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await callback.answer()
        return

    target = date.fromisoformat(callback.data.split(":")[1])
    try:
        # показуємо день у тому ж повідомленні (клавіатура з датами лишається, тож
        # можна гортати дати поспіль, а закрити — кнопкою «✖️ Скасувати»)
        await _render_master_day(callback.message, session, master, target, edit=True)
    except TelegramBadRequest:
        pass  # повторний тап на ту саму дату: Telegram не редагує незмінений текст
    await callback.answer()


# ── майстер: усі майбутні записи в одному списку (з можливістю скасувати) ──


async def _master_upcoming_payload(
    session: AsyncSession, master: Master
) -> tuple[str, InlineKeyboardMarkup]:
    """Усі майбутні активні записи майстра: текст + кнопки для скасування.

    Показує не лише «сьогодні / одна дата», а весь горизонт записів — щоб майстер
    бачив, коли в нього взагалі є клієнти. Тап по запису веде у звичайне
    підтвердження скасування (mcancel/mcancelyes).
    """
    bookings = await _upcoming_master_bookings(session, master.id)
    if not bookings:
        return "У вас немає активних майбутніх записів 🎉", master_upcoming_list_kb([])

    lines = []
    items = []
    for b in bookings:
        cname = b.client.full_name if b.client else "?"
        cphone = b.client.phone if b.client and b.client.phone else None
        sname = b.service.name if b.service else "?"
        tail = f" · 📞 {cphone}" if cphone else ""
        lines.append(f"🕐 {format_moment(b.start_at)} — {cname} ({sname}){tail}")
        items.append((b.id, f"🕐 {format_moment(b.start_at)} · {cname}"))

    text = (
        f"Найближчі записи ({len(bookings)}):\n"
        + "\n".join(lines)
        + "\n\nЩоб скасувати запис — тапніть на нього 👇"
    )
    return text, master_upcoming_list_kb(items)


@router.callback_query(MasterFlow.choosing_view_date, F.data == "mview:all")
async def master_view_all(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return

    text, kb = await _master_upcoming_payload(session, master)
    # той самий стан, що й у «❌ Скасувати запис клієнта» — щоб не дублювати флоу
    await state.set_state(MasterFlow.choosing_cancel_target)
    await state.update_data(cancel_all=True)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "mview:menu")
async def master_view_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Повернення зі списку всіх записів у підменю «📋 Записи»."""
    await state.set_state(MasterFlow.choosing_view_date)
    await state.update_data(cancel_all=False)
    try:
        await callback.message.edit_text(
            "Які записи показати?", reply_markup=master_bookings_menu_kb()
        )
    except TelegramBadRequest:
        pass  # той самий екран — Telegram відмовляється редагувати незмінений текст
    await callback.answer()


# ── вихідні: позначити або скасувати ──


async def _ask_which_dayoff(message: Message, state: FSMContext) -> None:
    await state.set_state(MasterFlow.choosing_dayoff_action)
    await message.answer("Що зробити з вихідними?", reply_markup=master_dayoff_menu_kb())


@router.message(F.text == MASTER_DAYOFF_BTN)
async def dayoff_menu(message: Message, state: FSMContext) -> None:
    await _ask_which_dayoff(message, state)


@router.message(F.text == MASTER_DAYOFF_MARK_TEXT)
async def dayoff_menu_legacy(message: Message, state: FSMContext) -> None:
    await _ask_which_dayoff(message, state)


@router.callback_query(MasterFlow.choosing_dayoff_action, F.data == "mdayoff:mark")
async def dayoff_mark_start(callback: CallbackQuery, state: FSMContext) -> None:
    today = datetime.now(TZ).date()
    await callback.message.edit_text(
        "На яку дату позначити вихідний?",
        reply_markup=dates_kb([today + timedelta(days=i) for i in range(30)], show_back=False, callback_prefix="dayoffdate"),
    )
    await state.set_state(MasterFlow.choosing_dayoff_date)
    await callback.answer()


@router.callback_query(MasterFlow.choosing_dayoff_date, F.data.startswith("dayoffdate:"))
async def dayoff_date_chosen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await callback.answer()
        return

    target = date.fromisoformat(callback.data.split(":")[1])

    affected = await mark_day_off(session, master.id, target)
    await session.commit()
    await state.clear()

    text = f"✅ Позначено вихідний: {format_date_human(target)}"
    if affected:
        text += f"\n⚠️ Автоматично скасовано {len(affected)} запис(ів) на цю дату, клієнтів сповіщено."
    await callback.message.edit_text(text)
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


@router.callback_query(MasterFlow.choosing_dayoff_action, F.data == "mdayoff:vacation")
async def master_vacation_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Введіть період відпустки у форматі <code>10.10.2026..20.10.2026</code>.\n"
        "Усі активні записи в цьому діапазоні будуть скасовані, клієнти отримають повідомлення."
    )
    await state.set_state(MasterFlow.entering_vacation_range)
    await callback.answer()


def _parse_vacation_range(raw: str) -> tuple[date, date]:
    parts = [x.strip() for x in raw.split("..", 1)]
    if len(parts) != 2:
        raise ValueError
    start = datetime.strptime(parts[0], "%d.%m.%Y").date()
    end = datetime.strptime(parts[1], "%d.%m.%Y").date()
    if end < start:
        start, end = end, start
    if (end - start).days > 366:
        raise ValueError
    return start, end


@router.message(MasterFlow.entering_vacation_range, TEXT_INPUT)
async def master_vacation_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, message.from_user.id)
    if master is None:
        await state.clear()
        return
    try:
        start, end = _parse_vacation_range(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("Не розпізнав період. Приклад: 10.10.2026..20.10.2026")
        return
    affected = await mark_days_off_range(session, master.id, start, end)
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
                    "Будь ласка, оберіть новий час через «📅 Записатися».",
                )
            except Exception:
                pass


@router.callback_query(MasterFlow.choosing_dayoff_action, F.data == "mdayoff:unmark")
async def dayoff_unmark_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return
    rows = (
        await session.scalars(
            select(DayOff).where(
                DayOff.master_id == master.id,
                DayOff.date >= datetime.now(TZ).date(),
            ).order_by(DayOff.date).limit(30)
        )
    ).all()
    if not rows:
        await state.clear()
        await callback.message.edit_text("У вас немає позначених вихідних 🙂")
        await callback.answer()
        return
    items = [(d.date.year * 10000 + d.date.month * 100 + d.date.day, f"🗓 {format_date_human(d.date)}") for d in rows]
    await callback.message.edit_text(
        "Який вихідний скасувати? (день знову стане робочим)",
        reply_markup=dayoff_list_kb(items),
    )
    await callback.answer()


@router.callback_query(MasterFlow.choosing_dayoff_action, F.data.startswith("mdayoffcancel:"))
async def dayoff_unmark_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return
    target = date.fromisoformat(callback.data.split(":")[1])
    row = await session.scalar(select(DayOff).where(DayOff.master_id == master.id, DayOff.date == target))
    if row is None:
        await state.clear()
        await callback.message.edit_text("Цей вихідний уже скасовано.")
        await callback.answer()
        return
    await session.delete(row)
    await session.commit()
    await state.clear()
    await callback.message.edit_text(f"✅ Вихідний {format_date_human(target)} скасовано — день знову робочий.")
    await callback.answer()


# ──────────────────────────── статус завершеного візиту ────────────────────────────

@router.message(F.text == MASTER_STATUS_BTN)
async def master_visit_status_list(message: Message, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, message.from_user.id)
    if master is None:
        return
    await state.clear()
    now = datetime.now(TZ)
    rows = (await session.scalars(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
            Booking.start_at >= now - timedelta(days=7),
            Booking.start_at <= now,
        ).order_by(Booking.start_at.desc()).limit(30)
    )).all()
    if not rows:
        await message.answer("Немає візитів за останні 7 днів, яким треба поставити статус.")
        return
    items = [(b.id, f"{format_moment(b.start_at)} — {b.client.full_name if b.client else '?'}") for b in rows]
    await message.answer(
        "Оберіть візит:", reply_markup=bookings_list_kb(items, callback_prefix="mstatuspick")
    )


@router.callback_query(F.data.startswith("mstatuspick:"))
async def master_visit_status_pick(callback: CallbackQuery, session: AsyncSession) -> None:
    master = await _get_master(session, callback.from_user.id)
    booking = await session.get(Booking, int(callback.data.split(":")[1]))
    if master is None or booking is None or booking.master_id != master.id:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"{booking.client.full_name if booking.client else '?'} — {format_moment(booking.start_at)}\nЯкий результат візиту?",
        reply_markup=master_visit_actions_kb(booking.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(("mstatusdone:", "mstatusnoshow:")))
async def master_visit_status_set(callback: CallbackQuery, session: AsyncSession) -> None:
    master = await _get_master(session, callback.from_user.id)
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    if master is None or booking is None or booking.master_id != master.id:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    if booking.status not in (BookingStatus.confirmed, BookingStatus.pending):
        await callback.answer("Статус цього запису вже змінено.", show_alert=True)
        return
    booking.status = BookingStatus.completed if callback.data.startswith("mstatusdone:") else BookingStatus.no_show
    await session.commit()
    label = "✅ Візит позначено завершеним." if booking.status == BookingStatus.completed else "🚫 Позначено no-show."
    await callback.message.edit_text(label)
    await callback.answer("Збережено")


# ──────────────────────────── "Скасувати запис клієнта" ────────────────────────────


async def _upcoming_master_bookings(session: AsyncSession, master_id: int) -> list[Booking]:
    return list(
        (
            await session.scalars(
                select(Booking)
                .where(
                    Booking.master_id == master_id,
                    Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
                    Booking.start_at >= datetime.now(TZ),
                )
                .order_by(Booking.start_at)
                .limit(30)
            )
        ).all()
    )


@router.message(F.text == MASTER_CANCEL_BTN)
async def cancel_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, message.from_user.id)
    if master is None:
        return

    bookings = await _upcoming_master_bookings(session, master.id)
    if not bookings:
        await message.answer("Немає активних майбутніх записів.")
        return

    await state.set_state(MasterFlow.choosing_cancel_date)
    await message.answer(
        "На який день показати записи для скасування?",
        reply_markup=dates_kb(
            [datetime.now(TZ).date() + timedelta(days=i) for i in range(30)],
            show_back=False,
            callback_prefix="mcancelday",
        ),
    )


async def _cancel_day_list(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, target: date
) -> None:
    """Показує активні записи обраного дня з кнопкою «обрати інший день»."""
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return

    now = datetime.now(TZ)
    bookings = [
        b for b in await _master_bookings_on_date(session, master.id, target) if b.start_at >= now
    ]

    if not bookings:
        await callback.message.edit_text(
            f"На {format_date_human(target)} активних записів немає.",
            reply_markup=dates_kb(
                [now.date() + timedelta(days=i) for i in range(30)],
                show_back=False,
                callback_prefix="mcancelday",
            ),
        )
        await state.set_state(MasterFlow.choosing_cancel_date)
        await callback.answer()
        return

    items = [
        (
            b.id,
            f"{format_moment(b.start_at)} — {b.client.full_name if b.client else '?'}",
        )
        for b in bookings
    ]
    await callback.message.edit_text(
        f"Записи на {format_date_human(target)} — який скасувати?",
        reply_markup=bookings_list_kb(
            items, callback_prefix="mcancel", back_callback="mcancelback"
        ),
    )
    await state.set_state(MasterFlow.choosing_cancel_target)
    await state.update_data(cancel_date=target.isoformat())
    await callback.answer()


@router.callback_query(MasterFlow.choosing_cancel_date, F.data.startswith("mcancelday:"))
async def cancel_day_selected(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    target = date.fromisoformat(callback.data.split(":")[1])
    await _cancel_day_list(callback, session, state, target)


@router.callback_query(F.data == "mcancelback")
async def cancel_back_to_days(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MasterFlow.choosing_cancel_date)
    today = datetime.now(TZ).date()
    await callback.message.edit_text(
        "На який день показати записи для скасування?",
        reply_markup=dates_kb(
            [today + timedelta(days=i) for i in range(30)],
            show_back=False,
            callback_prefix="mcancelday",
        ),
    )
    await callback.answer()


@router.callback_query(MasterFlow.choosing_cancel_target, F.data.startswith("mcancel:"))
async def cancel_select(callback: CallbackQuery, session: AsyncSession) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    if booking is None:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return

    client_name = booking.client.full_name if booking.client else "?"
    cphone = booking.client.phone if booking.client and booking.client.phone else None
    pline = f"\n📞 {cphone}" if cphone else ""
    await callback.message.edit_text(
        f"Скасувати запис {client_name} на {format_moment(booking.start_at)}?{pline}",
        reply_markup=yes_no_kb(f"mcancelyes:{booking_id}", "mcancelno"),
    )
    await callback.answer()


@router.callback_query(MasterFlow.choosing_cancel_target, F.data == "mcancelno")
async def cancel_no(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("cancel_all"):
        # «Ні, назад» зі списку всіх майбутніх записів -> повертаємось у цей самий список
        master = await _get_master(session, callback.from_user.id)
        if master is not None:
            text, kb = await _master_upcoming_payload(session, master)
            await callback.message.edit_text(text, reply_markup=kb)
            await callback.answer()
            return
    await state.set_state(MasterFlow.choosing_cancel_date)
    today = datetime.now(TZ).date()
    await callback.message.edit_text(
        "Гаразд, нічого не скасовано. На який день показати записи?",
        reply_markup=dates_kb(
            [today + timedelta(days=i) for i in range(30)],
            show_back=False,
            callback_prefix="mcancelday",
        ),
    )
    await callback.answer()


@router.callback_query(MasterFlow.choosing_cancel_target, F.data.startswith("mcancelyes:"))
async def cancel_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master = await _get_master(session, callback.from_user.id)
    if master is None:
        await state.clear()
        await callback.answer("Ви не майстер.", show_alert=True)
        return

    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    # ід перевіряємо ще й на «свій» — щоб застаріла кнопка з чужого екрана
    # не скасувала запис іншого майстра
    if booking is None or booking.master_id != master.id:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    if booking.status not in (BookingStatus.confirmed, BookingStatus.pending):
        await callback.answer("Цей запис уже не активний.", show_alert=True)
        return

    data = await state.get_data()
    back_to_list = bool(data.get("cancel_all"))
    moment = format_moment(booking.start_at)
    client = booking.client
    client_tg_id = client.tg_id if client else None

    booking.status = BookingStatus.cancelled_master
    await session.commit()

    if back_to_list:
        # лишаємось у флоу: показуємо оновлений список майбутніх записів
        text, kb = await _master_upcoming_payload(session, master)
        await callback.message.edit_text(
            f"✅ Запис на {moment} скасовано.\n\n{text}", reply_markup=kb
        )
    else:
        await state.clear()
        await callback.message.edit_text("✅ Запис скасовано.")
    await callback.answer()

    if client_tg_id:
        try:
            await callback.bot.send_message(
                client_tg_id,
                f"😔 Ваш запис на {moment} скасовано майстром.\n"
                f"Щоб обрати новий час — натисніть «📅 Записатися».",
            )
        except Exception:
            pass


# ──────────────────────────── "Робочі години" (запускається з owner.py) ────────────────────────────


@router.callback_query(F.data.startswith("ownerhours:"))
async def hours_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Кнопка в деталях майстра (owner.py) веде сюди."""
    master_id = int(callback.data.split(":")[1])
    master = await session.get(Master, master_id)
    if master is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    current = (
        await session.scalars(
            select(WorkingHours).where(WorkingHours.master_id == master_id).order_by(WorkingHours.weekday, WorkingHours.start_time)
        )
    ).all()

    if current:
        grouped: dict[int, list[str]] = {}
        for wh in current:
            grouped.setdefault(wh.weekday, []).append(
                f"{wh.start_time.strftime('%H:%M')}–{wh.end_time.strftime('%H:%M')}"
            )
        lines = [
            f"{WEEKDAY_FULL[weekday].capitalize()}: " + "; ".join(intervals)
            for weekday, intervals in sorted(grouped.items())
        ]
        current_text = "Поточний графік:\n" + "\n".join(lines)
    else:
        current_text = "Графік ще не задано."

    await state.update_data(hours_master_id=master_id)
    await callback.message.edit_text(
        f"{current_text}\n\n"
        f"Надішліть новий графік текстом у форматі:\n"
        f"<code>Пн-Пт 09:00-13:00;14:00-18:00, Сб 10:00-15:00, Нд вихідний</code>\n\n"
        f"Крапка з комою додає перерву в межах дня. Можна змінити лише потрібні дні.",
        reply_markup=owner_hours_cancel_kb(),
    )
    await state.set_state(MasterFlow.entering_hours)
    await callback.answer()


@router.callback_query(MasterFlow.entering_hours, F.data == "ownerhourscancel")
async def hours_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Гаразд, графік не змінено.")
    await callback.answer()


@router.message(MasterFlow.entering_hours, TEXT_INPUT)
async def hours_apply(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    master_id = data.get("hours_master_id")
    master = await session.get(Master, master_id) if master_id else None
    if master is None:
        await state.clear()
        await message.answer("Щось пішло не так, спробуйте ще раз через меню майстра.")
        return

    try:
        parsed = parse_working_hours_text(message.text)
    except ScheduleParseError as e:
        await message.answer(f"⚠️ {e}\n\nСпробуйте ще раз, наприклад:\nПн-Пт 09:00-18:00, Сб 10:00-15:00")
        return

    changed_days = []
    for weekday, value in parsed.items():
        existing_rows = (await session.scalars(
            select(WorkingHours).where(WorkingHours.master_id == master.id, WorkingHours.weekday == weekday)
        )).all()
        for row in existing_rows:
            await session.delete(row)
        if value is None:
            changed_days.append(f"{WEEKDAY_FULL[weekday].capitalize()}: вихідний")
        else:
            for start_time, end_time in value:
                session.add(WorkingHours(
                    master_id=master.id, weekday=weekday, start_time=start_time, end_time=end_time
                ))
            label = "; ".join(f"{a.strftime('%H:%M')}–{b.strftime('%H:%M')}" for a, b in value)
            changed_days.append(f"{WEEKDAY_FULL[weekday].capitalize()}: {label}")

    await session.commit()
    await state.clear()

    await message.answer("✅ Графік оновлено:\n" + "\n".join(changed_days))
