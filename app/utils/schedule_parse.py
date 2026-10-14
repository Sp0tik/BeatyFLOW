"""Парсер робочого графіка з підтримкою кількох інтервалів/перерв.

Приклади:
  Пн-Пт 09:00-18:00, Сб 10:00-15:00, Нд вихідний
  Пн-Пт 09:00-13:00;14:00-18:00, Сб 10:00-15:00

Кома розділяє правила для днів, крапка з комою — інтервали одного дня.
"""
import re
from datetime import time

WEEKDAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "нд": 6}
OFF_WORDS = {"вихідний", "выходной", "off", "вихідна"}


class ScheduleParseError(ValueError):
    pass


def _parse_weekday_token(token: str) -> int:
    key = token.strip().lower()
    if key not in WEEKDAY_MAP:
        raise ScheduleParseError(
            f"Не розпізнав день «{token}». Використовуйте: Пн, Вт, Ср, Чт, Пт, Сб, Нд"
        )
    return WEEKDAY_MAP[key]


def _weekday_range(start_token: str, end_token: str) -> list[int]:
    start = _parse_weekday_token(start_token)
    end = _parse_weekday_token(end_token)
    return list(range(start, end + 1)) if start <= end else list(range(start, 7)) + list(range(end + 1))


def _parse_time(token: str) -> time:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", token.strip())
    if not m:
        raise ScheduleParseError(f"Не розпізнав час «{token}». Формат: ГГ:ХХ")
    h, mi = map(int, m.groups())
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ScheduleParseError(f"Некоректний час «{token}»")
    return time(h, mi)


def _parse_interval(raw: str) -> tuple[time, time]:
    parts = raw.strip().split("-")
    if len(parts) != 2:
        raise ScheduleParseError(f"Не розпізнав інтервал «{raw}». Приклад: 09:00-13:00")
    start, end = _parse_time(parts[0]), _parse_time(parts[1])
    if start >= end:
        raise ScheduleParseError(f"Початок має бути раніше кінця в «{raw}»")
    return start, end


def parse_working_hours_text(text: str) -> dict[int, list[tuple[time, time]] | None]:
    result: dict[int, list[tuple[time, time]] | None] = {}
    segments = [s.strip() for s in text.split(",") if s.strip()]
    if not segments:
        raise ScheduleParseError("Порожній ввід. Приклад: Пн-Пт 09:00-18:00")

    for segment in segments:
        parts = segment.split(maxsplit=1)
        if len(parts) != 2:
            raise ScheduleParseError(f"Не розпізнав «{segment}»")
        day_part, rest = parts
        if "-" in day_part:
            a, b = day_part.split("-", 1)
            weekdays = _weekday_range(a, b)
        else:
            weekdays = [_parse_weekday_token(day_part)]

        if rest.strip().lower() in OFF_WORDS:
            for wd in weekdays:
                result[wd] = None
            continue

        intervals = [_parse_interval(x) for x in rest.split(";") if x.strip()]
        if not intervals:
            raise ScheduleParseError(f"Не вказано робочий час у «{segment}»")
        intervals.sort(key=lambda x: x[0])
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                raise ScheduleParseError(f"Інтервали перетинаються у «{segment}»")
        for wd in weekdays:
            result[wd] = list(intervals)
    return result
