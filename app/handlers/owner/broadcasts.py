"""Панель власника — розсилки клієнтам.

Кожна розсилка = текст + період у днях. Повідомлення йде через `період`
днів після останнього не скасованого візиту (див. app/services/broadcast.py).

Витягнуто з монолітного app/handlers/owner.py без зміни логіки.
"""

from html import escape as html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.filters import TEXT_INPUT
from app.handlers.owner.common import OwnerFlow, _edit_or_answer, _is_owner, _safe_edit
from app.keyboards import (
    OWNER_BROADCAST_BTN,
    owner_broadcast_detail_kb,
    owner_broadcast_period_kb,
    owner_broadcasts_list_kb,
    owner_cancel_kb,
    yes_no_kb,
)
from app.models import Broadcast, BroadcastSend
from app.services.broadcast import broadcast_recipients, deliver
from app.utils.db_text import decode_entities, encode_unstorable

router = Router(name="owner_broadcasts")


# ──────────────────────────── власник: розсилки ────────────────────────────
#
# Кожна розсилка = текст + період у днях. Графік індивідуальний для кожного
# клієнта: повідомлення йде через `період` днів після останнього не скасованого
# візиту (див. app/services/broadcast.py). Одержувачі — усі клієнти, крім
# майстрів і власника.


BROADCAST_TEXT_LIMIT = 4000  # запас до ліміту Telegram у 4096 симв.


def _bc_label(text: str, limit: int = 30) -> str:
    # у базі ємодзі лежать як &#128293;, а підпис кнопки HTML не розуміє — декодуємо.
    # НЕ екрануємо тут: текст кнопки Telegram показує як є (escape потрібен лише
    # там, де підпис вставляється в HTML-повідомлення — див. owner_broadcast_delete_start).
    first_line = " ".join(decode_entities(text).split())
    return first_line[:limit] + ("…" if len(first_line) > limit else "")


async def _broadcasts_payload(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    broadcasts = (await session.scalars(select(Broadcast).order_by(Broadcast.id))).all()
    recipients_count = len(await broadcast_recipients(session))

    items = [
        (bc.id, f"{'🟢' if bc.is_active else '⏸'} {_bc_label(bc.text)} · {bc.interval_days} дн.")
        for bc in broadcasts
    ]
    header = (
        f"📢 <b>Розсилки клієнтам</b>\n\n"
        f"Одержувачів: <b>{recipients_count}</b> (клієнти з увімкненими акціями/новинами; без майстрів і вас)\n"
        f"Графік: кожні N днів після останнього не скасованого візиту клієнта"
        f" (без візитів — після реєстрації), у межах робочого часу салону"
        f" {settings.broadcast_hour_start:02d}:00–{settings.broadcast_hour_end:02d}:00.\n\n"
    )
    footer = "Оберіть розсилку 👇" if broadcasts else "Розсилок ще немає — створіть першу 👇"
    return header + footer, owner_broadcasts_list_kb(items)


async def _broadcast_detail_payload(
    session: AsyncSession, broadcast: Broadcast
) -> tuple[str, InlineKeyboardMarkup]:
    recipients_count = len(await broadcast_recipients(session))
    status = "активна 🟢" if broadcast.is_active else "на паузі ⏸"
    sent_ok = (await session.scalar(select(func.count(BroadcastSend.id)).where(BroadcastSend.broadcast_id == broadcast.id, BroadcastSend.success.is_(True)))) or 0
    sent_failed = (await session.scalar(select(func.count(BroadcastSend.id)).where(BroadcastSend.broadcast_id == broadcast.id, BroadcastSend.success.is_(False)))) or 0
    text = (
        f"📢 <b>Розсилка №{broadcast.id}</b>\n"
        f"Статус: {status}\n"
        f"Період: кожні {broadcast.interval_days} дн.\n"
        f"Поточних одержувачів: {recipients_count}\n"
        f"Статистика відправок: ✅ {sent_ok} · ❌ {sent_failed}\n\n"
        f"————— текст —————\n{html_escape(decode_entities(broadcast.text))}"
    )
    return text, owner_broadcast_detail_kb(broadcast.id, broadcast.is_active)


async def _get_broadcast_or_warn(
    callback: CallbackQuery, session: AsyncSession
) -> Broadcast | None:
    broadcast_id = int(callback.data.split(":")[1])
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        await callback.answer("Розсилку не знайдено (можливо, її видалено).", show_alert=True)
    return broadcast


@router.message(F.text == OWNER_BROADCAST_BTN)
async def owner_broadcasts_open(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_owner(message.from_user.id):
        return
    await state.clear()
    text, kb = await _broadcasts_payload(session)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ownerbcast")
async def owner_broadcasts_list(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    text, kb = await _broadcasts_payload(session)
    await _safe_edit(callback.message, text, kb)
    await callback.answer()


# ── створення: текст -> період ──


@router.callback_query(F.data == "ownerbcastnew")
async def owner_broadcast_new_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await state.update_data(bc_return="ownerbcast")
    await callback.message.edit_text(
        "Надішліть <b>текст розсилки</b> — він прийде кожному клієнту окремим "
        "повідомленням.\n\nМожна використовувати HTML-теги Telegram: <b>жирний</b>, "
        "<i>курсив</i>, <a href=\"…\">посилання</a>.",
        reply_markup=owner_cancel_kb("ownerbcast"),
    )
    await state.set_state(OwnerFlow.broadcast_new_text)
    await callback.answer()


@router.message(OwnerFlow.broadcast_new_text, TEXT_INPUT)
async def owner_broadcast_new_text(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return
    text = message.text.strip()
    if not text:
        await message.answer("Текст не може бути порожнім. Спробуйте ще раз:")
        return
    if len(text) > BROADCAST_TEXT_LIMIT:
        await message.answer(
            f"Занадто довгий текст ({len(text)} симв.). Обріжте до {BROADCAST_TEXT_LIMIT} символів:"
        )
        return
    # ємодзі 🔥 (і символи на кшталт ✓ ⭐) база WIN1251 не зберігає — тримаємо їх
    # як числові HTML-сутності (&#128293;): Telegram читає розсилку в HTML-режимі,
    # тож клієнт бачить 🔥 (перевірено живим повідомленням у Telegram).
    encoded = await encode_unstorable(session, text)
    if len(encoded) > BROADCAST_TEXT_LIMIT:
        # сутність довша за символ — ліміт рахуємо по закодованому тексту
        await message.answer(
            f"Текст задовгий з урахуванням емодзі ({len(encoded)} симв.). "
            "Скоротіть текст або приберіть частину емодзі:"
        )
        return
    await state.update_data(bc_text=encoded)
    # Одразу показуємо, як текст побачить клієнт: сутності &#128293; Telegram
    # у HTML-режимі показує як 🔥 (перевірено живим повідомленням).
    # Якщо в тексті «зламаний» HTML — показуємо екранованим, щоб не впасти.
    try:
        await message.answer(
            f"👁 <b>Так текст побачить клієнт:</b>\n\n{encoded}\n\n"
            "💡 Можна використовувати HTML-теги Telegram: <b>жирний</b>, "
            "<i>курсив</i>, <a href=\"…\">посилання</a>, а також будь-які емодзі 🔥\n\n"
            "Оберіть, як часто надсилати цей текст кожному клієнту 👇",
            reply_markup=owner_broadcast_period_kb(
                preset_prefix="ownerbcnewfreq:",
                custom_callback="ownerbcnewcustom",
                cancel_callback="ownerbcast",
            ),
        )
    except TelegramBadRequest:
        await message.answer(
            "👁 <b>Так текст побачить клієнт</b> (HTML-теги показано як текст — "
            "перевірте їх):\n\n"
            f"{html_escape(decode_entities(encoded))}\n\n"
            "Оберіть, як часто надсилати цей текст кожному клієнту 👇",
            reply_markup=owner_broadcast_period_kb(
                preset_prefix="ownerbcnewfreq:",
                custom_callback="ownerbcnewcustom",
                cancel_callback="ownerbcast",
            ),
        )


async def _create_broadcast(session: AsyncSession, text: str, days: int) -> Broadcast:
    broadcast = Broadcast(text=text, interval_days=days, is_active=True)
    session.add(broadcast)
    await session.commit()
    return broadcast


# ── крок «період» для нової розсилки ──


@router.callback_query(F.data.startswith("ownerbcnewfreq:"))
async def owner_broadcast_new_freq(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return

    days_raw = callback.data.split(":")[1]
    data = await state.get_data()
    text = data.get("bc_text")
    if not text:
        await state.clear()
        await callback.answer(
            "Текст загублено (перезапуск бота). Почніть «➕ Нова розсилка» ще раз.",
            show_alert=True,
        )
        return
    if not days_raw.isdigit() or not 1 <= int(days_raw) <= 365:
        await callback.answer("Некоректний період.", show_alert=True)
        return

    broadcast = await _create_broadcast(session, text, int(days_raw))
    await state.clear()
    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await _safe_edit(callback.message, f"✅ Розсилку створено!\n\n{detail_text}", kb)
    await callback.answer()


@router.callback_query(F.data == "ownerbcnewcustom")
async def owner_broadcast_new_custom_days(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.update_data(bc_days_for="new")
    await _safe_edit(
        callback.message,
        "Введіть період у днях — ціле число від 1 до 365 (напр. 20):",
        owner_cancel_kb("ownerbcast"),
    )
    await state.set_state(OwnerFlow.broadcast_days)
    await callback.answer()


@router.message(OwnerFlow.broadcast_days, TEXT_INPUT)
async def owner_broadcast_days_typed(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return

    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 365:
        await message.answer("Не розпізнав період. Введіть ціле число днів від 1 до 365:")
        return
    days = int(raw)

    data = await state.get_data()
    target = data.get("bc_days_for", "new")
    await state.clear()

    if target == "new":
        text = data.get("bc_text")
        if not text:
            await message.answer(
                "Текст загублено (перезапуск бота). Почніть «➕ Нова розсилка» ще раз."
            )
            return
        broadcast = await _create_broadcast(session, text, days)
    else:
        broadcast = await session.get(Broadcast, int(target))
        if broadcast is None:
            await message.answer("Розсилку не знайдено (можливо, її видалено).")
            return
        broadcast.interval_days = days
        await session.commit()

    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await message.answer(detail_text, reply_markup=kb)

# ── деталі / керування розсилкою ──


@router.callback_query(F.data.startswith("ownerbcast:"))
async def owner_broadcast_detail(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return
    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await _safe_edit(callback.message, detail_text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ownerbctoggle:"))
async def owner_broadcast_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    broadcast.is_active = not broadcast.is_active
    await session.commit()
    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await _safe_edit(callback.message, detail_text, kb)
    await callback.answer("Активовано ▶️" if broadcast.is_active else "Призупинено ⏸")


@router.callback_query(F.data.startswith("ownerbctext:"))
async def owner_broadcast_edit_text_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    broadcast_id = int(callback.data.split(":")[1])
    await state.clear()
    await state.update_data(bc_edit_id=broadcast_id, bc_msg_id=callback.message.message_id)
    await _safe_edit(
        callback.message,
        "Надішліть <b>новий текст розсилки</b> (попередній буде замінений):",
        owner_cancel_kb(f"ownerbcast:{broadcast_id}"),
    )
    await state.set_state(OwnerFlow.broadcast_edit_text)
    await callback.answer()


@router.message(OwnerFlow.broadcast_edit_text, TEXT_INPUT)
async def owner_broadcast_edit_text_done(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(message.from_user.id):
        return
    text = message.text.strip()
    if not text:
        await message.answer("Текст не може бути порожнім. Спробуйте ще раз:")
        return
    if len(text) > BROADCAST_TEXT_LIMIT:
        await message.answer(
            f"Занадто довгий текст ({len(text)} симв.). Обріжте до {BROADCAST_TEXT_LIMIT} символів:"
        )
        return

    # див. owner_broadcast_new_text: ємодзі тримаємо як &#128293;, ліміт — після кодування
    encoded = await encode_unstorable(session, text)
    if len(encoded) > BROADCAST_TEXT_LIMIT:
        await message.answer(
            f"Текст задовгий з урахуванням емодзі ({len(encoded)} симв.). "
            "Скоротіть текст або приберіть частину емодзі:"
        )
        return

    data = await state.get_data()
    await state.clear()
    broadcast = await session.get(Broadcast, int(data["bc_edit_id"]))
    if broadcast is None:
        await message.answer("Розсилку не знайдено (можливо, її видалено).")
        return

    broadcast.text = encoded
    await session.commit()
    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await _edit_or_answer(
        message, data.get("bc_msg_id"), f"✅ Текст оновлено.\n\n{detail_text}", kb
    )


@router.callback_query(F.data.startswith("ownerbcfreq:"))
async def owner_broadcast_period_change(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    await _safe_edit(
        callback.message,
        f"Зараз: кожні {broadcast.interval_days} дн.\nОберіть новий період 👇",
        owner_broadcast_period_kb(
            preset_prefix=f"ownerbcfreqset:{broadcast.id}:",
            custom_callback=f"ownerbccustomfreq:{broadcast.id}",
            cancel_callback=f"ownerbcast:{broadcast.id}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownerbcfreqset:"))
async def owner_broadcast_period_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    _, id_raw, days_raw = callback.data.split(":")
    if not days_raw.isdigit() or not 1 <= int(days_raw) <= 365:
        await callback.answer("Некоректний період.", show_alert=True)
        return
    broadcast = await session.get(Broadcast, int(id_raw))
    if broadcast is None:
        await callback.answer("Розсилку не знайдено.", show_alert=True)
        return

    broadcast.interval_days = int(days_raw)
    await session.commit()
    detail_text, kb = await _broadcast_detail_payload(session, broadcast)
    await _safe_edit(callback.message, detail_text, kb)
    await callback.answer(f"Період: {broadcast.interval_days} дн.")


@router.callback_query(F.data.startswith("ownerbccustomfreq:"))
async def owner_broadcast_period_custom(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    broadcast_id = int(callback.data.split(":")[1])
    await state.update_data(bc_days_for=str(broadcast_id))
    await _safe_edit(
        callback.message,
        "Введіть період у днях — ціле число від 1 до 365 (напр. 20):",
        owner_cancel_kb(f"ownerbcast:{broadcast_id}"),
    )
    await state.set_state(OwnerFlow.broadcast_days)
    await callback.answer()


# ── термінова відправка та видалення ──


@router.callback_query(F.data.startswith("ownerbcsend:"))
async def owner_broadcast_send_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Підтвердження термінової відправки всім одержувачам просто зараз."""
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    recipients = await broadcast_recipients(session)
    if not recipients:
        await callback.answer("Клієнтів для розсилки поки немає.", show_alert=True)
        return

    await _safe_edit(
        callback.message,
        f"⚠️ Надіслати цей текст <b>просто зараз усім {len(recipients)} клієнтам</b>?\n\n"
        "Це не змінює звичний графік: після відправки відлік періоду в цих "
        "клієнтів почнеться заново.",
        yes_no_kb(f"ownerbcsendyes:{broadcast.id}", f"ownerbcast:{broadcast.id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownerbcsendyes:"))
async def owner_broadcast_send_now(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    recipients = await broadcast_recipients(session)
    sent, failed = await deliver(callback.bot, session, broadcast, recipients)
    await session.commit()

    status = "активна 🟢" if broadcast.is_active else "на паузі ⏸"
    summary = f"✅ Надіслано: <b>{sent}</b>"
    if failed:
        summary += f" · не дійшло (заблокували бота): <b>{failed}</b>"
    _, kb = await _broadcast_detail_payload(session, broadcast)
    await _safe_edit(
        callback.message,
        f"{summary}\n\n📢 Розсилка №{broadcast.id} · {status} · кожні {broadcast.interval_days} дн.",
        kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownerbcdel:"))
async def owner_broadcast_delete_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    await _safe_edit(
        callback.message,
        f"⚠️ Видалити розсилку №{broadcast.id}?\n\n{html_escape(_bc_label(broadcast.text, 200))}\n\n"
        "Історія надсилань буде видалена, розсилка більше не надходитиме.",
        yes_no_kb(f"ownerbcdelyes:{broadcast.id}", f"ownerbcast:{broadcast.id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownerbcdelyes:"))
async def owner_broadcast_delete_confirm(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    broadcast = await _get_broadcast_or_warn(callback, session)
    if broadcast is None:
        await callback.answer()
        return

    await session.execute(
        sa_delete(BroadcastSend).where(BroadcastSend.broadcast_id == broadcast.id)
    )
    await session.delete(broadcast)
    await session.commit()

    list_text, kb = await _broadcasts_payload(session)
    await _safe_edit(callback.message, f"✅ Розсилку видалено.\n\n{list_text}", kb)
    await callback.answer()
