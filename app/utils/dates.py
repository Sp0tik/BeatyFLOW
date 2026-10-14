from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings

TZ = ZoneInfo(settings.timezone)

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
WEEKDAY_FULL = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]
MONTH_NAMES = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]
MONTH_NAMES_NOM = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]


def format_date_human(d: date) -> str:
    """напр. '5 вересня, Пт'"""
    return f"{d.day} {MONTH_NAMES[d.month - 1]}, {WEEKDAY_SHORT[d.weekday()]}"


def format_date_short(d: date) -> str:
    """напр. '05.09 Пт' — для кнопок календаря"""
    return f"{d.day:02d}.{d.month:02d} {WEEKDAY_SHORT[d.weekday()]}"


def format_weekday_full(d: date) -> str:
    return WEEKDAY_FULL[d.weekday()]


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES_NOM[month - 1]} {year}"


# ──────────────────────────── час у таймзоні салону ────────────────────────────


def to_local(dt: datetime) -> datetime:
    """Приводить момент часу до таймзони салону.

    Час із БД (timestamptz) asyncpg віддає в UTC, тому без цього перетворення
    майстер бачив би на кілька годин інший час, ніж клієнт при записі.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def format_time(dt: datetime) -> str:
    """напр. '10:00' — у таймзоні салону"""
    return to_local(dt).strftime("%H:%M")


def format_moment(dt: datetime) -> str:
    """напр. '5 вересня, Пт о 10:00' — у таймзоні салону"""
    local = to_local(dt)
    return f"{format_date_human(local.date())} о {local.strftime('%H:%M')}"


def today_local() -> date:
    """Сьогоднішня дата за таймзоною салону (а не сервера)."""
    return datetime.now(TZ).date()
