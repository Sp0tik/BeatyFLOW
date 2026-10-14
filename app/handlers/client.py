from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.config import settings
from app.filters import NOT_MENU_TEXT
from app.keyboards import (
    CLIENT_BOOK_BTN,
    CLIENT_MY_BOOKINGS_BTN,
    CLIENT_SETTINGS_BTN,
    bookings_list_kb,
    client_menu_kb,
    client_settings_kb,
    client_booking_actions_kb,
    confirm_kb,
    dates_kb,
    master_menu_kb,
    masters_kb,
    services_kb,
    times_kb,
    yes_no_kb,
)
from app.models import Booking, BookingStatus, Client, Master, MasterService, Service
from app.services.booking import (
    SlotTakenError,
    cancel_booking,
    create_booking,
    get_or_create_client,
    reschedule_booking,
)
from app.services.slots import get_free_slots
from app.utils.dates import format_date_human, format_moment

router = Router(name="client")
TZ = ZoneInfo(settings.timezone)

KEEP_PHONE_TEXT = "✅ Залишити цей номер"
BACK_PHONE_TEXT = "◀️ Назад до часу"


class BookingFlow(StatesGroup):
    choosing_master = State()
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    entering_phone = State()
    confirming = State()
    reschedule_date = State()
    reschedule_time = State()


def _is_owner(tg_id: int) -> bool:
    return settings.owner_tg_id is not None and tg_id == settings.owner_tg_id


async def _persistent_menu(session: AsyncSession, tg_id: int) -> ReplyKeyboardMarkup:
    """Постійне меню нижньої панелі відповідно до ролі користувача.

    Використовується замість ReplyKeyboardRemove(): прибрану на кроці телефону
    клавіатуру потрібно повертати, інакше після завершення запису в чаті не
    лишається жодної кнопки і клієнт змушений писати /start.
    """
    is_owner = _is_owner(tg_id)
    master = await session.scalar(select(Master).where(Master.tg_id == tg_id))
    if master is not None:
        return master_menu_kb(is_owner=is_owner)
    return client_menu_kb(is_owner=is_owner)


# ──────────────────────────── /start і головне меню ────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    is_owner = _is_owner(message.from_user.id)

    master = await session.scalar(select(Master).where(Master.tg_id == message.from_user.id))
    if master is not None:
        await message.answer(
            f"З поверненням, {master.full_name}! 👋\nОберіть дію в меню знизу:",
            reply_markup=master_menu_kb(is_owner=is_owner),
        )
        return

    await message.answer(
        "Вітаємо! 💅 Я допоможу записатись у салон.\nОберіть дію в меню знизу:",
        reply_markup=client_menu_kb(is_owner=is_owner),
    )


@router.callback_query(F.data == "nav:cancel")
async def on_nav_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Скасовано.")
    await callback.answer()


@router.callback_query(F.data == "nav:noop")
async def on_nav_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ──────────────────────────── кнопка "Записатися" ────────────────────────────


@router.message(F.text == CLIENT_BOOK_BTN)
async def on_book_button(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    masters = (await session.scalars(select(Master).where(Master.is_active.is_(True)))).all()

    if not masters:
        await message.answer("Наразі немає доступних майстрів 😔 Спробуйте пізніше.")
        return

    await state.update_data(multi_master=len(masters) > 1)

    if len(masters) == 1:
        await _show_services(message, session, state, masters[0].id, edit=False)
        return

    await message.answer(
        "Оберіть майстра, до якого хочете записатись:",
        reply_markup=masters_kb([(m.id, m.full_name) for m in masters]),
    )
    await state.set_state(BookingFlow.choosing_master)


@router.callback_query(BookingFlow.choosing_master, F.data.startswith("master:"))
async def on_master_chosen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    master_id = int(callback.data.split(":")[1])
    await _show_services(callback.message, session, state, master_id, edit=True)
    await callback.answer()


# ──────────────────────────── крок: послуга ────────────────────────────


async def _show_services(
    message: Message, session: AsyncSession, state: FSMContext, master_id: int, edit: bool
) -> None:
    await state.update_data(master_id=master_id)

    rows = (
        await session.execute(
            select(Service.id, Service.name, MasterService.price, MasterService.duration_min)
            .join(MasterService, MasterService.service_id == Service.id)
            .where(MasterService.master_id == master_id, Service.is_active.is_(True))
        )
    ).all()

    if not rows:
        await message.answer("У цього майстра поки немає доступних послуг 😔")
        return

    data = await state.get_data()
    show_back = data.get("multi_master", False)

    text = "Оберіть послугу:"
    kb = services_kb([tuple(r) for r in rows], show_back=show_back)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
    await state.set_state(BookingFlow.choosing_service)


@router.callback_query(BookingFlow.choosing_service, F.data == "nav:back")
async def on_service_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    masters = (await session.scalars(select(Master).where(Master.is_active.is_(True)))).all()
    await callback.message.edit_text(
        "Оберіть майстра, до якого хочете записатись:",
        reply_markup=masters_kb([(m.id, m.full_name) for m in masters]),
    )
    await state.set_state(BookingFlow.choosing_master)
    await callback.answer()


@router.callback_query(BookingFlow.choosing_service, F.data.startswith("service:"))
async def on_service_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    service_id = int(callback.data.split(":")[1])
    await state.update_data(service_id=service_id)
    await _show_dates(callback.message, state, edit=True)
    await callback.answer()


# ──────────────────────────── крок: дата ────────────────────────────


async def _show_dates(message: Message, state: FSMContext, edit: bool) -> None:
    today = datetime.now(TZ).date()
    available_dates = [today + timedelta(days=i) for i in range(settings.booking_horizon_days)]

    text = "📅 Оберіть дату:"
    kb = dates_kb(available_dates, show_back=True)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
    await state.set_state(BookingFlow.choosing_date)


@router.callback_query(BookingFlow.choosing_date, F.data == "nav:back")
async def on_date_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await _show_services(callback.message, session, state, data["master_id"], edit=True)
    await callback.answer()


@router.callback_query(BookingFlow.choosing_date, F.data.startswith("date:"))
async def on_date_chosen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    target_date = date.fromisoformat(callback.data.split(":")[1])
    await state.update_data(target_date=target_date.isoformat())
    ok = await _show_times(callback.message, session, state, edit=True)
    if not ok:
        await callback.answer("На цю дату немає вільних слотів, оберіть іншу 😔", show_alert=True)
        return
    await callback.answer()


# ──────────────────────────── крок: час ────────────────────────────


async def _show_times(message: Message, session: AsyncSession, state: FSMContext, edit: bool) -> bool:
    data = await state.get_data()
    target_date = date.fromisoformat(data["target_date"])
    slots = await get_free_slots(session, data["master_id"], data["service_id"], target_date)

    if not slots:
        return False

    text = f"🕐 Вільний час на {format_date_human(target_date)}:"
    kb = times_kb(slots)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
    await state.set_state(BookingFlow.choosing_time)
    return True


@router.callback_query(BookingFlow.choosing_time, F.data == "nav:back")
async def on_time_back(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_dates(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(BookingFlow.choosing_time, F.data.startswith("time:"))
async def on_time_chosen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    start_at = datetime.fromisoformat(callback.data.split(":", 1)[1])
    await state.update_data(start_at=start_at.isoformat())

    client = await session.scalar(select(Client).where(Client.tg_id == callback.from_user.id))
    if client and client.phone:
        await state.update_data(phone=client.phone)
        await state.set_state(BookingFlow.entering_phone)
        await callback.message.answer(
            f"Використати збережений номер {client.phone}? Або надiшліть новий кнопкою чи текстом:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📱 Надіслати номер телефону", request_contact=True)],
                    [KeyboardButton(text=KEEP_PHONE_TEXT)],
                    [KeyboardButton(text=BACK_PHONE_TEXT)],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        await callback.answer()
        return

    await callback.message.delete()
    contact_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати номер телефону", request_contact=True)],
            [KeyboardButton(text=BACK_PHONE_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(
        "Майже готово! Поділіться номером телефону для підтвердження запису 👇",
        reply_markup=contact_kb,
    )
    await state.set_state(BookingFlow.entering_phone)
    await callback.answer()


# ──────────────────────────── крок: телефон ────────────────────────────


@router.message(BookingFlow.entering_phone, F.text == KEEP_PHONE_TEXT)
async def on_phone_keep(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("phone"):
        await message.answer("Щось пішло не так, спробуйте ще раз.")
        await state.clear()
        return
    await message.answer(
        "Добре, лишаємо збережений номер 👍",
        reply_markup=await _persistent_menu(session, message.from_user.id),
    )
    await _show_confirmation(message, state, edit=False)


@router.message(BookingFlow.entering_phone, F.text == BACK_PHONE_TEXT)
async def on_phone_back(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await message.answer(
        "Повертаємось до вибору часу…",
        reply_markup=await _persistent_menu(session, message.from_user.id),
    )
    await _show_times(message, session, state, edit=False)


@router.message(BookingFlow.entering_phone, NOT_MENU_TEXT)
async def on_phone_typed(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.contact:
        phone = message.contact.phone_number
    elif message.text and message.text.strip().replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit():
        phone = message.text.strip()
    else:
        await message.answer("Надішліть номер кнопкою «📱 Надіслати номер телефону» або введіть цифрами 👇")
        return
    client = await get_or_create_client(session, message.from_user.id, message.from_user.full_name)
    client.phone = phone
    await session.commit()
    await state.update_data(phone=phone)
    await message.answer(
        "Дякуємо! 🙌",
        reply_markup=await _persistent_menu(session, message.from_user.id),
    )
    await _show_confirmation(message, state, edit=False)


# ──────────────────────────── крок: підтвердження ────────────────────────────


async def _show_confirmation(message: Message, state: FSMContext, edit: bool) -> None:
    data = await state.get_data()
    start_at = datetime.fromisoformat(data["start_at"])

    text = (
        f"📋 <b>Підтвердіть запис:</b>\n\n"
        f"🗓 {format_moment(start_at)}\n\n"
        f"Все вірно?"
    )
    kb = confirm_kb()
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
    await state.set_state(BookingFlow.confirming)


@router.callback_query(BookingFlow.confirming, F.data == "nav:back")
async def on_confirm_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    ok = await _show_times(callback.message, session, state, edit=True)
    if not ok:
        await callback.message.edit_text("На жаль, вільних слотів на цю дату більше немає 😔")
        await state.clear()
    await callback.answer()


@router.callback_query(BookingFlow.confirming, F.data == "confirm")
async def on_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    client = await get_or_create_client(session, callback.from_user.id, callback.from_user.full_name)
    start_at = datetime.fromisoformat(data["start_at"])

    try:
        await create_booking(session, client.id, data["master_id"], data["service_id"], start_at)
        await session.commit()
    except SlotTakenError:
        await session.rollback()
        await callback.message.edit_text("На жаль, цей час щойно зайняли 😔 Натисніть «📅 Записатися» ще раз.")
        await state.clear()
        await callback.answer()
        return

    await callback.message.edit_text(
        f"✅ Запис підтверджено на {format_moment(start_at)}!\n"
        f"Нагадаємо вам заздалегідь. До зустрічі! 💅"
    )
    await state.clear()
    await callback.answer("Готово!")

    master = await session.get(Master, data["master_id"])
    if master and master.tg_id:
        try:
            await callback.bot.send_message(
                master.tg_id,
                f"🆕 Новий запис!\n"
                f"👤 {client.full_name}" + (f" · {client.phone}" if client.phone else "") + "\n"
                f"🗓 {format_moment(start_at)}",
            )
        except Exception:
            pass


# ──────────────────────────── кнопка "Мої записи" (+ скасування) ────────────────────────────


async def _active_bookings(session: AsyncSession, client_id: int) -> list[Booking]:
    return list(
        (
            await session.scalars(
                select(Booking)
                .where(
                    Booking.client_id == client_id,
                    Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
                    Booking.start_at >= datetime.now(TZ),
                )
                .order_by(Booking.start_at)
            )
        ).all()
    )


async def _render_my_bookings(message: Message, session: AsyncSession, tg_id: int) -> None:
    """Список активних записів клієнта.

    tg_id передаємо явно: якщо функція викликана з callback, то `message` — це
    повідомлення бота, і його `from_user.id` — id самого бота, а не клієнта.
    """
    client = await session.scalar(select(Client).where(Client.tg_id == tg_id))
    if client is None:
        await message.answer("У вас ще немає записів. Натисніть «📅 Записатися», щоб створити перший!")
        return

    bookings = await _active_bookings(session, client.id)
    if not bookings:
        await message.answer("У вас немає активних записів. Натисніть «📅 Записатися»!")
        return

    items = [
        (b.id, f"🗓 {format_moment(b.start_at)}")
        for b in bookings
    ]
    await message.answer(
        "Ваші активні записи (натисніть, щоб відкрити):",
        reply_markup=bookings_list_kb(items, callback_prefix="cbooking"),
    )


@router.message(F.text == CLIENT_MY_BOOKINGS_BTN)
async def my_bookings(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()  # вихід із кроків введення (напр. номера телефону)
    await _render_my_bookings(message, session, message.from_user.id)


@router.callback_query(F.data.startswith("cbooking:"))
async def on_client_booking_open(callback: CallbackQuery, session: AsyncSession) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    client = booking.client if booking else None
    if (
        booking is None
        or client is None
        or client.tg_id != callback.from_user.id
        or booking.status not in (BookingStatus.pending, BookingStatus.confirmed)
    ):
        await callback.answer("Цей запис вже недоступний.", show_alert=True)
        return
    service_name = booking.service.name if booking.service else "Послуга"
    master = await session.get(Master, booking.master_id)
    master_name = master.full_name if master else "Майстер"
    await callback.message.edit_text(
        f"<b>{service_name}</b>\n💇‍♀️ {master_name}\n🗓 {format_moment(booking.start_at)}",
        reply_markup=client_booking_actions_kb(booking.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cresched:"))
async def client_reschedule_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    client = booking.client if booking else None
    if booking is None or client is None or client.tg_id != callback.from_user.id:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    await state.update_data(
        reschedule_booking_id=booking.id, master_id=booking.master_id, service_id=booking.service_id
    )
    today = datetime.now(TZ).date()
    dates = [today + timedelta(days=i) for i in range(settings.booking_horizon_days)]
    await callback.message.edit_text(
        "📅 Оберіть нову дату:",
        reply_markup=dates_kb(dates, show_back=False, callback_prefix="rdate"),
    )
    await state.set_state(BookingFlow.reschedule_date)
    await callback.answer()


@router.callback_query(BookingFlow.reschedule_date, F.data.startswith("rdate:"))
async def client_reschedule_date(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    target = date.fromisoformat(callback.data.split(":", 1)[1])
    data = await state.get_data()
    slots = await get_free_slots(
        session, data["master_id"], data["service_id"], target,
        exclude_booking_id=data["reschedule_booking_id"],
    )
    if not slots:
        await callback.answer("На цю дату немає вільного часу.", show_alert=True)
        return
    await callback.message.edit_text(
        f"🕐 Вільний час на {format_date_human(target)}:",
        reply_markup=times_kb(
            slots, callback_prefix="rtime", back_callback=f"cresched:{data['reschedule_booking_id']}"
        ),
    )
    await state.set_state(BookingFlow.reschedule_time)
    await callback.answer()


@router.callback_query(BookingFlow.reschedule_time, F.data.startswith("rtime:"))
async def client_reschedule_finish(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    booking = await session.get(Booking, data.get("reschedule_booking_id"))
    if booking is None or booking.client.tg_id != callback.from_user.id:
        await state.clear()
        await callback.answer("Запис не знайдено.", show_alert=True)
        return
    new_start = datetime.fromisoformat(callback.data.split(":", 1)[1])
    old_start = booking.start_at
    try:
        await reschedule_booking(session, booking, new_start)
        await session.commit()
    except SlotTakenError:
        await session.rollback()
        await callback.answer("Цей час уже недоступний. Оберіть інший.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        f"✅ Запис перенесено з {format_moment(old_start)} на {format_moment(new_start)}."
    )
    master = await session.get(Master, booking.master_id)
    if master and master.tg_id:
        try:
            await callback.bot.send_message(
                master.tg_id,
                f"🔄 Клієнт переніс запис: {format_moment(old_start)} → {format_moment(new_start)}.",
            )
        except Exception:
            pass
    await callback.answer("Перенесено")


@router.callback_query(F.data.startswith("ccancel:"))
async def on_client_cancel_select(callback: CallbackQuery, session: AsyncSession) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    client = booking.client if booking else None
    if (
        booking is None
        or client is None
        or client.tg_id != callback.from_user.id
        or booking.status not in (BookingStatus.pending, BookingStatus.confirmed)
    ):
        await callback.answer("Цей запис вже неактивний.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Скасувати запис на {format_moment(booking.start_at)}?",
        reply_markup=yes_no_kb(f"ccancelyes:{booking_id}", "ccancelno"),
    )
    await callback.answer()


@router.callback_query(F.data == "ccancelno")
async def on_client_cancel_no(callback: CallbackQuery, session: AsyncSession) -> None:
    # callback.message — повідомлення бота, тому клієнта шукаємо за callback.from_user.id,
    # а не за callback.message.from_user.id (там id самого бота).
    await _render_my_bookings(callback.message, session, callback.from_user.id)
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("ccancelyes:"))
async def on_client_cancel_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = await session.get(Booking, booking_id)
    client = booking.client if booking else None
    if (
        booking is None
        or client is None
        or client.tg_id != callback.from_user.id
        or booking.status not in (BookingStatus.pending, BookingStatus.confirmed)
    ):
        await callback.answer("Цей запис вже неактивний.", show_alert=True)
        return

    await cancel_booking(session, booking, by="client")
    await session.commit()
    await callback.message.edit_text("✅ Запис скасовано.")
    await callback.answer()

    master = await session.get(Master, booking.master_id)
    if master and master.tg_id:
        try:
            await callback.bot.send_message(
                master.tg_id,
                f"⚠️ Клієнт скасував запис на {format_moment(booking.start_at)}.",
            )
        except Exception:
            pass


# ──────────────────────── налаштування клієнта ────────────────────────

@router.message(F.text == CLIENT_SETTINGS_BTN)
async def client_settings(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    client = await get_or_create_client(session, message.from_user.id, message.from_user.full_name)
    await session.commit()
    status = "увімкнені ✅" if client.marketing_opt_in else "вимкнені 🔕"
    await message.answer(
        f"⚙️ <b>Налаштування</b>\n\nАкції та новини: {status}\n"
        "Нагадування про ваші записи залишаються службовими й не вимикаються цією кнопкою.",
        reply_markup=client_settings_kb(client.marketing_opt_in),
    )


@router.callback_query(F.data == "clientmarketingtoggle")
async def client_marketing_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    client = await session.scalar(select(Client).where(Client.tg_id == callback.from_user.id))
    if client is None:
        await callback.answer("Спочатку натисніть /start.", show_alert=True)
        return
    client.marketing_opt_in = not client.marketing_opt_in
    await session.commit()
    status = "увімкнені ✅" if client.marketing_opt_in else "вимкнені 🔕"
    await callback.message.edit_text(
        f"⚙️ <b>Налаштування</b>\n\nАкції та новини: {status}\n"
        "Нагадування про ваші записи залишаються службовими й не вимикаються цією кнопкою.",
        reply_markup=client_settings_kb(client.marketing_opt_in),
    )
    await callback.answer("Збережено")


# ──────────────────────── тап по кнопці зі старого меню ────────────────────────


@router.callback_query(
    F.data.startswith(
        ("date:", "rdate:", "rtime:", "dayoffdate:", "mview:", "mviewdate:", "mdayoff:", "mdayoffcancel:", "time:", "master:", "service:", "mcancel:", "mcancelyes:")
    )
)
async def on_stale_button(callback: CallbackQuery) -> None:
    """Кнопка з уже неактуального меню (у чаті могла лишитись стара клавіатура).

    Хендлери конкретних флоу зареєстровані раніше й мають фільтр за станом, тож
    сюди потрапляє лише те, що вже нічого не означає. Без цього хендлера Telegram
    безкінечно крутив би «годинник» на такому тапі.
    """
    await callback.answer("Це меню вже неактуальне — скористайтесь кнопками внизу 👇")
