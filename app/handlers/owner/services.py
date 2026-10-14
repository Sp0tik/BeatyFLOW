"""Панель власника — послуги: каталог і індивідуальні ціни майстра.

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import TEXT_INPUT
from app.handlers.owner.common import OwnerFlow, _edit_or_answer, _is_owner
from app.keyboards import (
    OWNER_SERVICES_BTN,
    owner_cancel_kb,
    owner_master_service_add_kb,
    owner_master_service_detail_kb,
    owner_master_services_kb,
    owner_service_delete_confirm_kb,
    owner_service_detail_kb,
    owner_services_list_kb,
)
from app.models import Booking, Master, MasterService, Service
from app.utils.db_text import storable_problem

router = Router(name="owner_services")


# ──────────────────── послуги окремого майстра (індивідуальні ціни) ────────────────────


async def _master_services_payload(
    session: AsyncSession, master_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    """(текст, клавіатура) зі списком послуг саме цього майстра."""
    master = await session.get(Master, master_id)
    rows = (
        await session.execute(
            select(Service.id, Service.name, MasterService.price, MasterService.duration_min)
            .join(MasterService, MasterService.service_id == Service.id)
            .where(MasterService.master_id == master_id)
            .order_by(Service.id)
        )
    ).all()
    assigned = [(r[0], r[1], float(r[2]), int(r[3])) for r in rows]
    name = master.full_name if master else "?"
    if assigned:
        text = f"Послуги майстра «{name}» (ціна/тривалість — саме його):"
    else:
        text = f"У майстра «{name}» ще немає підключених послуг — додайте 👇"
    return text, owner_master_services_kb(master_id, assigned)


@router.callback_query(F.data.startswith("ownermsvc:"))
async def owner_master_services(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    master_id = int(callback.data.split(":")[1])
    if await session.get(Master, master_id) is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return
    text, kb = await _master_services_payload(session, master_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ownerms:"))
async def owner_master_service_detail(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Деталі послуги в майстра: 'ownerms:<master_id>:<service_id>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    await state.clear()  # перехід у деталі = вихід із кроків введення ціни
    _, master_raw, service_raw = callback.data.split(":")
    master_id, service_id = int(master_raw), int(service_raw)

    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
        )
    )
    if ms is None:
        await callback.answer("Послугу не знайдено в цього майстра.", show_alert=True)
        return

    service = await session.get(Service, service_id)
    name = service.name if service else "?"
    await callback.message.edit_text(
        f"<b>{name}</b>\nЦіна: {float(ms.price):.0f}₴\nТривалість: {ms.duration_min} хв",
        reply_markup=owner_master_service_detail_kb(master_id, service_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownermsvcadd:"))
async def owner_master_service_add_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Показати активні послуги каталогу, яких ще нема в майстра."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    master_id = int(callback.data.split(":")[1])
    if await session.get(Master, master_id) is None:
        await callback.answer("Майстра не знайдено.", show_alert=True)
        return

    assigned_ids = set(
        (
            await session.scalars(
                select(MasterService.service_id).where(MasterService.master_id == master_id)
            )
        ).all()
    )
    catalog = (
        await session.execute(
            select(Service.id, Service.name)
            .where(Service.is_active.is_(True))
            .order_by(Service.id)
        )
    ).all()
    available = [(sid, sname) for sid, sname in catalog if sid not in assigned_ids]

    if not available:
        await callback.answer("Усі активні послуги вже підключені цьому майстру.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "Оберіть послугу для додавання майстру:",
        reply_markup=owner_master_service_add_kb(master_id, available),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownermsvcaddpick:"))
async def owner_master_service_add_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """'ownermsvcaddpick:<master>:<service>' -> FSM: ціна, потім тривалість."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, master_raw, service_raw = callback.data.split(":")
    await state.update_data(
        ms_master_id=int(master_raw),
        ms_service_id=int(service_raw),
        ms_msg_id=callback.message.message_id,
    )
    await callback.message.edit_text(
        "Введіть ціну цієї послуги для майстра в гривнях (напр. 350):",
        reply_markup=owner_cancel_kb(f"ownermsvc:{master_raw}"),
    )
    await state.set_state(OwnerFlow.adding_ms_price)
    await callback.answer()


@router.message(OwnerFlow.adding_ms_price, TEXT_INPUT)
async def owner_master_service_add_price(message: Message, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    price = _parse_positive_number(message.text)
    if price is None:
        await message.answer("Не розпізнав ціну. Введіть додатне число, напр. 350:")
        return
    await state.update_data(ms_price=price)
    data = await state.get_data()
    await message.answer(
        "Введіть тривалість цієї послуги для майстра в хвилинах (напр. 60):",
        reply_markup=owner_cancel_kb(f"ownermsvc:{data['ms_master_id']}"),
    )
    await state.set_state(OwnerFlow.adding_ms_duration)




@router.message(OwnerFlow.adding_ms_duration, TEXT_INPUT)
async def owner_master_service_add_finish(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return

    duration_raw = message.text.strip()
    if not duration_raw.isdigit() or int(duration_raw) <= 0:
        await message.answer("Не розпізнав тривалість. Введіть ціле число хвилин, напр. 60:")
        return
    duration = int(duration_raw)

    data = await state.get_data()
    master_id = data["ms_master_id"]
    service_id = data["ms_service_id"]
    price = data["ms_price"]
    msg_id = data.get("ms_msg_id")

    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
        )
    )
    if ms is None:
        session.add(
            MasterService(
                master_id=master_id, service_id=service_id, price=price, duration_min=duration
            )
        )
    else:
        ms.price = price
        ms.duration_min = duration
    await session.commit()
    await state.clear()

    service = await session.get(Service, service_id)
    name = service.name if service else "послугу"
    list_text, kb = await _master_services_payload(session, master_id)
    await _edit_or_answer(
        message,
        msg_id,
        f"✅ «{name}» для майстра: {price:.0f}₴, {duration} хв\n\n{list_text}",
        kb,
    )


@router.callback_query(F.data.startswith("ownermsvcprice:"))
async def owner_master_service_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """'ownermsvcprice:<master>:<service>' -> FSM: нова ціна, потім тривалість."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, master_raw, service_raw = callback.data.split(":")
    await state.update_data(
        ms_master_id=int(master_raw),
        ms_service_id=int(service_raw),
        ms_msg_id=callback.message.message_id,
    )
    await callback.message.edit_text(
        "Введіть нову ціну цієї послуги для майстра в гривнях (напр. 350):",
        reply_markup=owner_cancel_kb(f"ownerms:{master_raw}:{service_raw}"),
    )
    await state.set_state(OwnerFlow.editing_ms_price)
    await callback.answer()


@router.message(OwnerFlow.editing_ms_price, TEXT_INPUT)
async def owner_master_service_edit_price(message: Message, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    price = _parse_positive_number(message.text)
    if price is None:
        await message.answer("Не розпізнав ціну. Введіть додатне число, напр. 350:")
        return
    await state.update_data(ms_price=price)
    data = await state.get_data()
    await message.answer(
        "Введіть нову тривалість цієї послуги для майстра в хвилинах (напр. 60):",
        reply_markup=owner_cancel_kb(
            f"ownerms:{data['ms_master_id']}:{data['ms_service_id']}"
        ),
    )
    await state.set_state(OwnerFlow.editing_ms_duration)


@router.message(OwnerFlow.editing_ms_duration, TEXT_INPUT)
async def owner_master_service_edit_finish(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return

    duration_raw = message.text.strip()
    if not duration_raw.isdigit() or int(duration_raw) <= 0:
        await message.answer("Не розпізнав тривалість. Введіть ціле число хвилин, напр. 60:")
        return
    duration = int(duration_raw)

    data = await state.get_data()
    master_id = data["ms_master_id"]
    service_id = data["ms_service_id"]
    price = data["ms_price"]
    msg_id = data.get("ms_msg_id")

    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
        )
    )
    if ms is None:
        await state.clear()
        await message.answer("Послугу не знайдено в цього майстра.")
        return
    ms.price = price
    ms.duration_min = duration
    await session.commit()
    await state.clear()

    service = await session.get(Service, service_id)
    name = service.name if service else "послугу"
    await _edit_or_answer(
        message,
        msg_id,
        f"<b>{name}</b>\nЦіна: {price:.0f}₴\nТривалість: {duration} хв\n\n✅ Оновлено для цього майстра.",
        owner_master_service_detail_kb(master_id, service_id),
    )


@router.callback_query(F.data.startswith("ownermsvcdel:"))
async def owner_master_service_remove(callback: CallbackQuery, session: AsyncSession) -> None:
    """Прибрати послугу в майстра (рядок master_services, каталог не чіпаємо)."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    _, master_raw, service_raw = callback.data.split(":")
    master_id, service_id = int(master_raw), int(service_raw)

    ms = await session.scalar(
        select(MasterService).where(
            MasterService.master_id == master_id,
            MasterService.service_id == service_id,
        )
    )
    if ms is None:
        await callback.answer("Послугу не знайдено в цього майстра.", show_alert=True)
        return

    await session.delete(ms)
    await session.commit()

    text, kb = await _master_services_payload(session, master_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Послугу прибрано в майстра")


# ──────────────────────────── список послуг ────────────────────────────


async def _render_services_list(message: Message, session: AsyncSession, edit: bool) -> None:
    rows = (
        await session.execute(
            select(
                Service.id,
                Service.name,
                Service.is_active,
                func.count(MasterService.id),
            )
            .outerjoin(MasterService, MasterService.service_id == Service.id)
            .group_by(Service.id)
            .order_by(Service.id)
        )
    ).all()
    items = [tuple(r) for r in rows]

    text = "Послуги салону:" if items else "Послуг ще немає — додайте першу 👇"
    kb = owner_services_list_kb(items)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.message(F.text == OWNER_SERVICES_BTN)
async def owner_services(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    await state.clear()  # вихід із кроків введення ціни/назви
    await _render_services_list(message, session, edit=False)


@router.callback_query(F.data == "ownerservicesback")
async def owner_services_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await _render_services_list(callback.message, session, edit=True)
    await callback.answer()


# ──────────────────────────── додати послугу ────────────────────────────


@router.callback_query(F.data == "owneraddservice")
async def owner_add_service_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_text(
        "Введіть назву послуги (напр. «Манікюр класичний»):",
        reply_markup=owner_cancel_kb("ownerservicesback"),
    )
    await state.set_state(OwnerFlow.entering_service_name)
    await callback.answer()


@router.message(OwnerFlow.entering_service_name, TEXT_INPUT)
async def owner_add_service_name(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return
    name = message.text.strip()
    if not name:
        await message.answer("Назва не може бути порожньою, спробуйте ще раз:")
        return
    problem = await storable_problem(session, name)
    if problem:
        await message.answer(problem)
        return
    await state.update_data(new_service_name=name)
    await message.answer(
        "Введіть ціну послуги в гривнях (лише число, напр. 350):",
        reply_markup=owner_cancel_kb("ownerservicesback"),
    )
    await state.set_state(OwnerFlow.entering_service_price)


def _parse_positive_number(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


@router.message(OwnerFlow.entering_service_price, TEXT_INPUT)
async def owner_add_service_price(message: Message, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    price = _parse_positive_number(message.text)
    if price is None:
        await message.answer("Не розпізнав ціну. Введіть додатне число, напр. 350:")
        return
    await state.update_data(new_service_price=price)
    await message.answer(
        "Введіть тривалість послуги в хвилинах (ціле число, напр. 60):",
        reply_markup=owner_cancel_kb("ownerservicesback"),
    )
    await state.set_state(OwnerFlow.entering_service_duration)


@router.message(OwnerFlow.entering_service_duration, TEXT_INPUT)
async def owner_add_service_duration(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return

    duration_raw = message.text.strip()
    if not duration_raw.isdigit() or int(duration_raw) <= 0:
        await message.answer("Не розпізнав тривалість. Введіть ціле число хвилин, напр. 60:")
        return
    duration = int(duration_raw)

    data = await state.get_data()
    name = data["new_service_name"]
    price = data["new_service_price"]

    service = Service(name=name, is_active=True)
    session.add(service)
    await session.flush()

    masters = (await session.scalars(select(Master).where(Master.is_active.is_(True)))).all()
    for master in masters:
        session.add(
            MasterService(master_id=master.id, service_id=service.id, price=price, duration_min=duration)
        )

    await session.commit()
    await state.clear()

    masters_note = (
        f"Підключено {len(masters)} майстр(ам)." if masters else "Активних майстрів поки немає — підключиться автоматично, коли додасте майстра."
    )
    await message.answer(
        f"✅ Послугу «{name}» додано: {price:.0f}₴, {duration} хв.\n{masters_note}"
    )
    await _render_services_list(message, session, edit=False)


# ──────────────────────────── деталі послуги ────────────────────────────


@router.callback_query(F.data.startswith("ownerservice:"))
async def owner_service_detail(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    await state.clear()  # перехід у деталі = вихід із кроків введення
    service_id = int(callback.data.split(":")[1])
    service = await session.get(Service, service_id)
    if service is None:
        await callback.answer("Послугу не знайдено.", show_alert=True)
        return

    assignments = (
        await session.scalars(select(MasterService).where(MasterService.service_id == service_id))
    ).all()

    status = "активна 🟢" if service.is_active else "деактивована ⚪️"
    if assignments:
        lines = []
        for a in assignments:
            master = await session.get(Master, a.master_id)
            master_name = master.full_name if master else "?"
            lines.append(f"— {master_name}: {a.price:.0f}₴, {a.duration_min} хв")
        assignments_text = "\n".join(lines)
    else:
        assignments_text = "Ще не підключена жодному майстру."

    await callback.message.edit_text(
        f"<b>{service.name}</b>\nСтатус: {status}\n\n{assignments_text}",
        reply_markup=owner_service_detail_kb(service.id, service.is_active),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownersvctoggle:"))
async def owner_toggle_service(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    service_id = int(callback.data.split(":")[1])
    service = await session.get(Service, service_id)
    if service is None:
        await callback.answer("Послугу не знайдено.", show_alert=True)
        return

    service.is_active = not service.is_active
    await session.commit()
    await owner_service_detail(callback, session, state)


@router.callback_query(F.data.startswith("ownersvcedit:"))
async def owner_edit_service_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    service_id = int(callback.data.split(":")[1])
    await state.update_data(editing_service_id=service_id)
    await callback.message.edit_text(
        "Введіть нову ціну в гривнях (застосується до всіх майстрів, що надають цю послугу):",
        reply_markup=owner_cancel_kb(f"ownerservice:{service_id}"),
    )
    await state.set_state(OwnerFlow.editing_service_price)
    await callback.answer()


@router.message(OwnerFlow.editing_service_price, TEXT_INPUT)
async def owner_edit_service_price(message: Message, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    price = _parse_positive_number(message.text)
    if price is None:
        await message.answer("Не розпізнав ціну. Введіть додатне число, напр. 350:")
        return
    await state.update_data(editing_service_price=price)
    data = await state.get_data()
    await message.answer(
        "Введіть нову тривалість у хвилинах:",
        reply_markup=owner_cancel_kb(f"ownerservice:{data['editing_service_id']}"),
    )
    await state.set_state(OwnerFlow.editing_service_duration)


@router.message(OwnerFlow.editing_service_duration, TEXT_INPUT)
async def owner_edit_service_duration(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return

    duration_raw = message.text.strip()
    if not duration_raw.isdigit() or int(duration_raw) <= 0:
        await message.answer("Не розпізнав тривалість. Введіть ціле число хвилин:")
        return
    duration = int(duration_raw)

    data = await state.get_data()
    service_id = data["editing_service_id"]
    price = data["editing_service_price"]

    assignments = (
        await session.scalars(select(MasterService).where(MasterService.service_id == service_id))
    ).all()
    for a in assignments:
        a.price = price
        a.duration_min = duration

    await session.commit()
    await state.clear()

    service = await session.get(Service, service_id)
    await message.answer(f"✅ Оновлено «{service.name}»: {price:.0f}₴, {duration} хв для {len(assignments)} майстр(ів).")
    await _render_services_list(message, session, edit=False)



# ──────────────────────────── видалення послуги ────────────────────────────


@router.callback_query(F.data.startswith("ownersvcdel:"))
async def owner_service_delete_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Екран підтвердження: 'ownersvcdel:<service_id>'."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    service_id = int(callback.data.split(":")[1])
    service = await session.get(Service, service_id)
    if service is None:
        await callback.answer("Послугу не знайдено.", show_alert=True)
        return

    bookings_count = (
        await session.scalar(select(func.count(Booking.id)).where(Booking.service_id == service_id))
    ) or 0
    if bookings_count:
        await callback.answer(
            f"⛔ На цю послугу є {bookings_count} запис(ів) в історії — її неможливо "
            "видалити. Краще деактивуйте (⏸).",
            show_alert=True,
        )
        return

    await state.clear()
    await callback.message.edit_text(
        f"⚠️ Видалити послугу «{service.name}» назавжди?\n\n"
        "Вона зникне з каталогу і у всіх майстрів. Дію неможливо скасувати.",
        reply_markup=owner_service_delete_confirm_kb(service_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownersvcdelyes:"))
async def owner_service_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """'ownersvcdelyes:<service_id>' — видалення каталогу і зв'язків."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    service_id = int(callback.data.split(":")[1])
    service = await session.get(Service, service_id)
    if service is None:
        await callback.answer("Послугу не знайдено.", show_alert=True)
        return

    bookings_count = (
        await session.scalar(select(func.count(Booking.id)).where(Booking.service_id == service_id))
    ) or 0
    if bookings_count:
        await callback.answer(
            f"⛔ З'явились записи ({bookings_count}) — видалення скасовано.",
            show_alert=True,
        )
        return

    await session.execute(sa_delete(MasterService).where(MasterService.service_id == service_id))
    await session.execute(sa_delete(Service).where(Service.id == service_id))
    await session.commit()

    await callback.answer(f"✅ Послугу «{service.name}» видалено")
    await _render_services_list(callback.message, session, edit=True)
