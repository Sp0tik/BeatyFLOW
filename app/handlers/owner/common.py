"""Спільні дрібниці для підмодулів панелі власника.

Тут лише те, що потрібне більш ніж одному модулю панелі: перевірка «це
власник?», таймзона салону, спільний FSM-стан і крихітні хелпери
редагування повідомлень. Решта хелперів живе поруч із хендлерами, які їх
використовують.
"""

from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, Message

from app.config import settings

TZ = ZoneInfo(settings.timezone)


class OwnerFlow(StatesGroup):
    entering_master_name = State()
    entering_service_name = State()
    entering_service_price = State()
    entering_service_duration = State()
    editing_service_price = State()
    editing_service_duration = State()
    # індивідуальні ціни/тривалість конкретного майстра
    adding_ms_price = State()
    adding_ms_duration = State()
    editing_ms_price = State()
    editing_ms_duration = State()
    # розсилки
    broadcast_new_text = State()
    broadcast_edit_text = State()
    broadcast_days = State()
    entering_vacation_range = State()


def _is_owner(tg_id: int) -> bool:
    """Чи належить Telegram-id власнику панелі (з налаштувань)."""
    return settings.owner_tg_id is not None and tg_id == settings.owner_tg_id


async def _safe_edit(message: Message, text: str, kb: InlineKeyboardMarkup) -> None:
    """edit_text, який не падає, якщо вміст повідомлення не змінився."""
    try:
        await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


async def _edit_or_answer(
    message: Message, msg_id: int | None, text: str, kb: InlineKeyboardMarkup
) -> None:
    """Оновити inline-повідомлення, з якого стартував FSM; інакше — надіслати нове."""
    if msg_id is not None:
        try:
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=msg_id, reply_markup=kb
            )
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=kb)
