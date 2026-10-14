from datetime import date, datetime

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.utils.dates import format_date_short, today_local

MASTER_EMOJI = "💇‍♀️"
SERVICE_EMOJI = "💅"
BACK_TEXT = "◀️ Назад"
CANCEL_TEXT = "✖️ Скасувати"

# Тексти кнопок постійного меню знизу — і як текст кнопки, і як значення фільтра F.text.
CLIENT_BOOK_BTN = "📅 Записатися"
CLIENT_MY_BOOKINGS_BTN = "📖 Мої записи"
CLIENT_SETTINGS_BTN = "⚙️ Налаштування"

MASTER_BOOKINGS_BTN = "📋 Записи"
MASTER_DAYOFF_BTN = "🗓 Вихідні"
MASTER_CANCEL_BTN = "❌ Скасувати запис клієнта"
MASTER_STATUS_BTN = "📌 Статус візиту"

# Старі тексти (залишені для зворотної сумісності — у когось може лишитися
# стара клавіатура в чаті; хендлери їх теж обробляють).
MASTER_TODAY_BTN = "📋 Записи на сьогодні"
MASTER_OTHER_DAY_BTN = "📅 Записи на іншу дату"
MASTER_DAYOFF_MARK_TEXT = "🗓 Позначити вихідний"

OWNER_MANAGE_BTN = "⚙️ Керування майстрами"
OWNER_ADD_MASTER_BTN = "➕ Додати майстра"
OWNER_SERVICES_BTN = "🧾 Послуги та ціни"
OWNER_ADD_SERVICE_BTN = "➕ Додати послугу"
OWNER_BROADCAST_BTN = "📢 Розсилки"
OWNER_ANALYTICS_BTN = "📊 Аналітика"
OWNER_CLIENTS_BTN = "👥 Клієнти"

KEEP_PHONE_TEXT = "✅ Залишити цей номер"
BACK_PHONE_TEXT = "◀️ Назад до часу"

# Усі тексти кнопок постійної (reply) клавіатури. Хендлери FSM-станів мусять
# їх ігнорувати (~F.text.in_(MENU_TEXTS)), інакше натиск кнопки меню під час
# введення ціни/тривалості сприймається як введене значення — звідси й помилка
# «Не розпізнав ціну…» після «Змінити ціну».
MENU_TEXTS = frozenset(
    {
        CLIENT_BOOK_BTN,
        CLIENT_MY_BOOKINGS_BTN,
        CLIENT_SETTINGS_BTN,
        MASTER_BOOKINGS_BTN,
        MASTER_DAYOFF_BTN,
        MASTER_CANCEL_BTN,
        MASTER_STATUS_BTN,
        MASTER_TODAY_BTN,
        MASTER_OTHER_DAY_BTN,
        MASTER_DAYOFF_MARK_TEXT,
        OWNER_MANAGE_BTN,
        OWNER_ADD_MASTER_BTN,
        OWNER_SERVICES_BTN,
        OWNER_ADD_SERVICE_BTN,
        OWNER_BROADCAST_BTN,
        OWNER_ANALYTICS_BTN,
        OWNER_CLIENTS_BTN,
        KEEP_PHONE_TEXT,
        BACK_PHONE_TEXT,
    }
)


def client_menu_kb(is_owner: bool = False) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=CLIENT_BOOK_BTN)
    kb.button(text=CLIENT_MY_BOOKINGS_BTN)
    kb.button(text=CLIENT_SETTINGS_BTN)
    kb.adjust(2, 1)
    if is_owner:
        kb.row(KeyboardButton(text=OWNER_MANAGE_BTN))
        kb.row(KeyboardButton(text=OWNER_SERVICES_BTN))
        kb.row(KeyboardButton(text=OWNER_BROADCAST_BTN))
        kb.row(KeyboardButton(text=OWNER_ANALYTICS_BTN), KeyboardButton(text=OWNER_CLIENTS_BTN))
    return kb.as_markup(resize_keyboard=True, is_persistent=True)


def master_menu_kb(is_owner: bool = False) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=MASTER_BOOKINGS_BTN)
    kb.button(text=MASTER_DAYOFF_BTN)
    kb.button(text=MASTER_CANCEL_BTN)
    kb.button(text=MASTER_STATUS_BTN)
    kb.adjust(1)
    if is_owner:
        kb.row(KeyboardButton(text=OWNER_MANAGE_BTN))
        kb.row(KeyboardButton(text=OWNER_SERVICES_BTN))
        kb.row(KeyboardButton(text=OWNER_BROADCAST_BTN))
        kb.row(KeyboardButton(text=OWNER_ANALYTICS_BTN), KeyboardButton(text=OWNER_CLIENTS_BTN))
    return kb.as_markup(resize_keyboard=True, is_persistent=True)


# ── майстер: записи / вихідні (інлайн-підменю) ──

MASTER_VIEW_TODAY = "📋 Сьогодні"
MASTER_VIEW_PICK_DATE = "📅 Обрати дату"
MASTER_VIEW_ALL = "📋 Усі майбутні"
MASTER_DAYOFF_MARK = "🗓 Позначити вихідний"
MASTER_DAYOFF_UNMARK = "↩️ Скасувати вихідний"


def master_bookings_menu_kb() -> InlineKeyboardMarkup:
    """Підменю кнопки «📋 Записи»: сьогодні, конкретна дата або всі майбутні."""
    kb = InlineKeyboardBuilder()
    kb.button(text=MASTER_VIEW_TODAY, callback_data="mview:today")
    kb.button(text=MASTER_VIEW_PICK_DATE, callback_data="mview:pick")
    kb.button(text=MASTER_VIEW_ALL, callback_data="mview:all")
    kb.adjust(1)
    return kb.as_markup()


def master_upcoming_list_kb(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Усі майбутні записи майстра: (booking_id, label) -> 'mcancel:<booking_id>'.

    Порожній список дає лише кнопку повернення в меню записів.
    Скасування йде тим самим флоу, що й «❌ Скасувати запис клієнта»:
    тап по запису -> підтвердження -> cancelled_master + повідомлення клієнту.
    """
    kb = InlineKeyboardBuilder()
    for booking_id, label in items:
        kb.button(text=label, callback_data=f"mcancel:{booking_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="◀️ Меню записів", callback_data="mview:menu"))
    return kb.as_markup()


def master_visit_actions_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Візит завершено", callback_data=f"mstatusdone:{booking_id}")
    kb.button(text="🚫 Клієнт не прийшов", callback_data=f"mstatusnoshow:{booking_id}")
    kb.adjust(1)
    return kb.as_markup()


def master_dayoff_menu_kb() -> InlineKeyboardMarkup:
    """Підменю кнопки «🗓 Вихідні»: позначити або скасувати."""
    kb = InlineKeyboardBuilder()
    kb.button(text=MASTER_DAYOFF_MARK, callback_data="mdayoff:mark")
    kb.button(text=MASTER_DAYOFF_UNMARK, callback_data="mdayoff:unmark")
    kb.button(text="🏖 Відпустка на період", callback_data="mdayoff:vacation")
    kb.adjust(1)
    return kb.as_markup()


def dayoff_list_kb(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Список вихідних для скасування: [(iso-дата, label)] -> 'mdayoffcancel:<iso>'."""
    kb = InlineKeyboardBuilder()
    for iso, label in items:
        kb.button(text=label, callback_data=f"mdayoffcancel:{iso}")
    kb.adjust(1)
    return kb.as_markup()




def masters_kb(masters: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for master_id, name in masters:
        kb.button(text=f"{MASTER_EMOJI} {name}", callback_data=f"master:{master_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=CANCEL_TEXT, callback_data="nav:cancel"))
    return kb.as_markup()


def services_kb(services: list[tuple[int, str, float, int]], show_back: bool = True) -> InlineKeyboardMarkup:
    """services: (service_id, name, price, duration_min)"""
    kb = InlineKeyboardBuilder()
    for service_id, name, price, duration in services:
        kb.button(
            text=f"{SERVICE_EMOJI} {name} · {price:.0f}₴ · {duration}хв",
            callback_data=f"service:{service_id}",
        )
    kb.adjust(1)
    nav_row = [InlineKeyboardButton(text=BACK_TEXT, callback_data="nav:back")] if show_back else []
    nav_row.append(InlineKeyboardButton(text=CANCEL_TEXT, callback_data="nav:cancel"))
    kb.row(*nav_row)
    return kb.as_markup()


def dates_kb(
    available_dates: list[date], show_back: bool = True, callback_prefix: str = "date"
) -> InlineKeyboardMarkup:
    """Кнопки дат -> callback '{callback_prefix}:{iso-дата}'.

    Префікс різний для різних флоу: кнопка з уже неактуального меню не повинна
    випадково спрацювати в іншому флоу (напр., тап по «перегляду записів» у стані
    «позначити вихідний» не має права скасовувати записи того дня).

    Дати без кнопки «✖️ Скасувати» (show_back=False) — це меню з гортанням:
    день показується в тому ж повідомленні, клавіатура лишається активною.
    """
    kb = InlineKeyboardBuilder()
    today = today_local()
    for d in available_dates:
        if d == today:
            label = f"🔵 Сьогодні {d.strftime('%d.%m')}"
        elif (d - today).days == 1:
            label = f"Завтра {d.strftime('%d.%m')}"
        else:
            label = format_date_short(d)
        kb.button(text=label, callback_data=f"{callback_prefix}:{d.isoformat()}")
    kb.adjust(2)
    nav_row = [InlineKeyboardButton(text=BACK_TEXT, callback_data="nav:back")] if show_back else []
    nav_row.append(InlineKeyboardButton(text=CANCEL_TEXT, callback_data="nav:cancel"))
    kb.row(*nav_row)
    return kb.as_markup()


def _period_of_day(dt: datetime) -> str:
    h = dt.hour
    if h < 12:
        return "🌅 Ранок"
    if h < 17:
        return "🌤 День"
    return "🌆 Вечір"


def times_kb(
    slots: list[datetime],
    callback_prefix: str = "time",
    back_callback: str = "nav:back",
    cancel_callback: str = "nav:cancel",
) -> InlineKeyboardMarkup:
    """Групує слоти за періодом дня, по 4 кнопки часу в рядку."""
    rows: list[list[InlineKeyboardButton]] = []
    current_period: str | None = None
    time_row: list[InlineKeyboardButton] = []

    def flush() -> None:
        nonlocal time_row
        if time_row:
            rows.append(time_row)
            time_row = []

    for s in slots:
        period = _period_of_day(s)
        if period != current_period:
            flush()
            rows.append([InlineKeyboardButton(text=f"— {period} —", callback_data="nav:noop")])
            current_period = period
        time_row.append(InlineKeyboardButton(text=s.strftime("%H:%M"), callback_data=f"{callback_prefix}:{s.isoformat()}"))
        if len(time_row) == 4:
            flush()
    flush()

    rows.append(
        [
            InlineKeyboardButton(text=BACK_TEXT, callback_data=back_callback),
            InlineKeyboardButton(text=CANCEL_TEXT, callback_data=cancel_callback),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_booking_actions_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Перенести запис", callback_data=f"cresched:{booking_id}")
    kb.button(text="❌ Скасувати запис", callback_data=f"ccancel:{booking_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Підтвердити запис", callback_data="confirm"))
    kb.row(
        InlineKeyboardButton(text=BACK_TEXT, callback_data="nav:back"),
        InlineKeyboardButton(text=CANCEL_TEXT, callback_data="nav:cancel"),
    )
    return kb.as_markup()


def bookings_list_kb(
    bookings: list[tuple[int, str]], callback_prefix: str, back_callback: str | None = None
) -> InlineKeyboardMarkup:
    """bookings: (booking_id, label). Кожен пункт -> callback '{prefix}:{id}'.

    back_callback — додаткова кнопка «назад» унизу списку (напр. обрати інший день).
    """
    kb = InlineKeyboardBuilder()
    for booking_id, label in bookings:
        kb.button(text=label, callback_data=f"{callback_prefix}:{booking_id}")
    kb.adjust(1)
    if back_callback:
        kb.row(InlineKeyboardButton(text="◀️ Обрати інший день", callback_data=back_callback))
    return kb.as_markup()


def yes_no_kb(yes_callback: str, no_callback: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так", callback_data=yes_callback)
    kb.button(text="◀️ Ні, назад", callback_data=no_callback)
    kb.adjust(2)
    return kb.as_markup()


def client_settings_kb(marketing_opt_in: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    label = "🔕 Вимкнути акції та новини" if marketing_opt_in else "🔔 Увімкнути акції та новини"
    kb.button(text=label, callback_data="clientmarketingtoggle")
    return kb.as_markup()


def owner_clients_list_kb(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for client_id, label in items:
        kb.button(text=label, callback_data=f"ownerclient:{client_id}")
    kb.adjust(1)
    return kb.as_markup()


# ──────────────────────────── власник: майстри ────────────────────────────


def owner_masters_list_kb(masters: list[tuple[int, str, bool]]) -> InlineKeyboardMarkup:
    """masters: (id, name, is_active)"""
    kb = InlineKeyboardBuilder()
    for master_id, name, is_active in masters:
        status = "🟢" if is_active else "⚪️"
        kb.button(text=f"{status} {name}", callback_data=f"ownermaster:{master_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=OWNER_ADD_MASTER_BTN, callback_data="owneraddmaster"))
    return kb.as_markup()


def owner_master_detail_kb(master_id: int, is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Записи майстра", callback_data=f"ownermbook:{master_id}")
    kb.button(text="🧾 Послуги та ціни майстра", callback_data=f"ownermsvc:{master_id}")
    kb.button(text="🕐 Робочі години", callback_data=f"ownerhours:{master_id}")
    kb.button(text="🗓 Вихідні майстра", callback_data=f"ownerdayoff:{master_id}")
    toggle = "⏸ Деактивувати майстра" if is_active else "▶️ Активувати майстра"
    kb.button(text=toggle, callback_data=f"ownermtoggle:{master_id}")
    kb.button(text="🔄 Новий код авторизації", callback_data=f"ownerregen:{master_id}")
    kb.button(text="🗑 Видалити майстра", callback_data=f"ownerdelmaster:{master_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data="ownerback"))
    return kb.as_markup()


def owner_master_bookings_kb(master_id: int, items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Майбутні записи майстра: (booking_id, label) -> 'ownermbookpick:<mid>:<bid>'.

    Порожній список дає саму лише кнопку повернення до картки майстра.
    """
    kb = InlineKeyboardBuilder()
    for booking_id, label in items:
        kb.button(text=label, callback_data=f"ownermbookpick:{master_id}:{booking_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownermaster:{master_id}"))
    return kb.as_markup()


def owner_dayoff_menu_kb(master_id: int, has_days_off: bool) -> InlineKeyboardMarkup:
    """Екран керування вихідними конкретного майстра (панель власника)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Позначити вихідний", callback_data=f"ownerdayoffadd:{master_id}")
    kb.button(text="🏖 Відпустка на період", callback_data=f"ownerdayoffvac:{master_id}")
    if has_days_off:
        kb.button(text="↩️ Скасувати вихідний", callback_data=f"ownerdayoffunmark:{master_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownermaster:{master_id}"))
    return kb.as_markup()


def owner_dayoff_dates_kb(master_id: int, available_dates: list[date]) -> InlineKeyboardMarkup:
    """Пікер дати для позначення вихідного: 'ownerdayoffdate:<master_id>:<iso>'.

    Від dates_kb відрізняється тим, що кнопка «назад» веде на екран вихідних
    конкретного майстра, а не на загальний nav:back.
    """
    kb = InlineKeyboardBuilder()
    today = today_local()
    for d in available_dates:
        if d == today:
            label = f"🔵 Сьогодні {d.strftime('%d.%m')}"
        elif (d - today).days == 1:
            label = f"Завтра {d.strftime('%d.%m')}"
        else:
            label = format_date_short(d)
        kb.button(text=label, callback_data=f"ownerdayoffdate:{master_id}:{d.isoformat()}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownerdayoff:{master_id}"),
        InlineKeyboardButton(text=CANCEL_TEXT, callback_data=f"ownerdayoff:{master_id}"),
    )
    return kb.as_markup()


def owner_dayoff_list_kb(master_id: int, items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Список вихідних для скасування: [(iso-дата, label)] -> 'ownerdayoffcancel:<mid>:<iso>'."""
    kb = InlineKeyboardBuilder()
    for iso, label in items:
        kb.button(text=label, callback_data=f"ownerdayoffcancel:{master_id}:{iso}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownerdayoff:{master_id}"))
    return kb.as_markup()


def owner_hours_cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=CANCEL_TEXT, callback_data="ownerhourscancel")
    return kb.as_markup()


def owner_cancel_kb(back_callback: str) -> InlineKeyboardMarkup:
    """Кнопка «✖️ Скасувати» на кроках текстового введення FSM.

    Без неї після «Змінити ціну» хендлер стану «з'їдав» будь-який текст,
    включно з кнопками меню, і відповідав «Не розпізнав ціну…».
    `back_callback` повертає на попередній екран і чистить стан.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=CANCEL_TEXT, callback_data=back_callback)
    return kb.as_markup()


# ──────────────────────────── власник: розсилки ────────────────────────────


def owner_broadcasts_list_kb(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """items: (broadcast_id, label). Кнопка створення завжди внизу."""
    kb = InlineKeyboardBuilder()
    for bc_id, label in items:
        kb.button(text=label, callback_data=f"ownerbcast:{bc_id}")
    if items:
        kb.adjust(1)
    kb.row(InlineKeyboardButton(text="➕ Нова розсилка", callback_data="ownerbcastnew"))
    return kb.as_markup()


def owner_broadcast_detail_kb(broadcast_id: int, is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    toggle = "⏸ Пауза" if is_active else "▶️ Увімкнути"
    kb.button(text=toggle, callback_data=f"ownerbctoggle:{broadcast_id}")
    kb.button(text="✏️ Змінити текст", callback_data=f"ownerbctext:{broadcast_id}")
    kb.button(text="🔁 Змінити період", callback_data=f"ownerbcfreq:{broadcast_id}")
    kb.button(text="📨 Надіслати зараз усім", callback_data=f"ownerbcsend:{broadcast_id}")
    kb.button(text="🗑 Видалити", callback_data=f"ownerbcdel:{broadcast_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data="ownerbcast"))
    return kb.as_markup()


def owner_broadcast_period_kb(
    preset_prefix: str, custom_callback: str, cancel_callback: str
) -> InlineKeyboardMarkup:
    """Пресети періоду розсилки. preset_prefix: 'ownerbcnewfreq:' або 'ownerbcfreqset:<id>:'."""
    kb = InlineKeyboardBuilder()
    for days, label in (
        (7, "🔁 Кожні 7 днів (щотижня)"),
        (15, "🔁 Кожні 15 днів (≈2 рази/місяць)"),
        (30, "🔁 Кожні 30 днів (раз на місяць)"),
    ):
        kb.button(text=label, callback_data=f"{preset_prefix}{days}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="✏️ Ввести свій період", callback_data=custom_callback))
    kb.row(InlineKeyboardButton(text=CANCEL_TEXT, callback_data=cancel_callback))
    return kb.as_markup()


# ──────────────────────────── власник: послуги ────────────────────────────


def owner_services_list_kb(services: list[tuple[int, str, bool, int]]) -> InlineKeyboardMarkup:
    """services: (id, name, is_active, masters_count)"""
    kb = InlineKeyboardBuilder()
    for service_id, name, is_active, masters_count in services:
        status = "🟢" if is_active else "⚪️"
        kb.button(
            text=f"{status} {name} ({masters_count} майстр.)",
            callback_data=f"ownerservice:{service_id}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=OWNER_ADD_SERVICE_BTN, callback_data="owneraddservice"))
    return kb.as_markup()


# ──────────────────────────── власник: послуги окремого майстра ────────────────────────────


def owner_master_services_kb(
    master_id: int, assigned: list[tuple[int, str, float, int]]
) -> InlineKeyboardMarkup:
    """Послуги майстра: (service_id, name, price, duration_min).

    Тап по послузі -> деталі/редагування/відв'язка; окрема кнопка — додати.
    """
    kb = InlineKeyboardBuilder()
    for service_id, name, price, duration in assigned:
        kb.button(
            text=f"💅 {name} · {price:.0f}₴ · {duration}хв",
            callback_data=f"ownerms:{master_id}:{service_id}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="➕ Додати послугу", callback_data=f"ownermsvcadd:{master_id}"))
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownermaster:{master_id}"))
    return kb.as_markup()


def owner_master_service_add_kb(
    master_id: int, available: list[tuple[int, str]]
) -> InlineKeyboardMarkup:
    """Послуги з каталогу, яких у майстра ще немає -> 'ownermsvcaddpick:<master>:<service>'."""
    kb = InlineKeyboardBuilder()
    for service_id, name in available:
        kb.button(text=f"➕ {name}", callback_data=f"ownermsvcaddpick:{master_id}:{service_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownermsvc:{master_id}"))
    return kb.as_markup()


def owner_master_service_detail_kb(master_id: int, service_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Змінити ціну/тривалість", callback_data=f"ownermsvcprice:{master_id}:{service_id}")
    kb.button(text="➖ Прибрати послугу в майстра", callback_data=f"ownermsvcdel:{master_id}:{service_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data=f"ownermsvc:{master_id}"))
    return kb.as_markup()


def owner_master_delete_confirm_kb(master_id: int) -> InlineKeyboardMarkup:
    """Підтвердження видалення майстра: так/ні."""
    return yes_no_kb(f"ownerdelmasteryes:{master_id}", f"ownermaster:{master_id}")


def owner_service_delete_confirm_kb(service_id: int) -> InlineKeyboardMarkup:
    """Підтвердження видалення послуги: так/ні."""
    return yes_no_kb(f"ownersvcdelyes:{service_id}", f"ownerservice:{service_id}")


def owner_service_detail_kb(service_id: int, is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    toggle_text = "⏸ Деактивувати" if is_active else "▶️ Активувати"
    kb.button(text=toggle_text, callback_data=f"ownersvctoggle:{service_id}")
    kb.button(text="💰 Змінити ціну/тривалість", callback_data=f"ownersvcedit:{service_id}")
    kb.button(text="🗑 Видалити послугу", callback_data=f"ownersvcdel:{service_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK_TEXT, callback_data="ownerservicesback"))
    return kb.as_markup()
