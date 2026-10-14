"""Обмеження кодування бази даних для тексту, який надсилають користувачі.

Якщо кластер Postgres створений у кодуванні WIN1251 (типова ситуація для
Windows-машин з кирилицею), символи поза Windows-1251 — емодзі, ✓, ⭐,
математичний мінус — база зберігати не вміє: INSERT/UPDATE падає з
«untranslatable character», а користувач бачить лише «бот зламався».

Для WIN1251 множина символів, які приймає Postgres, збігається з Python-кодеком
cp1251 (перевірено на 38 символах: кирилиця, «» — – № • … ™ €, ємодзі, ✓, ⭐),
тому перевірка локальна, без запитів на кожен символ. У базі UTF8 перевірка
вимикається взагалі — там вміщується все.
"""

import re

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# назва кодування Postgres -> Python-кодек; None = перевіряти нічого (UTF8 вміщує все)
_PYTHON_CODECS = {
    "UTF8": None,
    "WIN1251": "cp1251",
    "WIN1250": "cp1250",
    "LATIN1": "latin_1",
    "LATIN2": "latin_2",
    "SQL_ASCII": None,
}

# скільки «поганих» символів показувати у повідомленні, щоб не забити екран
_MAX_LISTED = 6

_database_codec: str | None = None
_database_checked = False


async def database_codec(session: AsyncSession) -> str | None:
    """Python-кодек кодування бази; None — якщо будь-який текст збережеться."""
    global _database_codec, _database_checked
    if not _database_checked:
        name = (
            await session.execute(
                sa.text(
                    "SELECT pg_encoding_to_char(encoding) FROM pg_database "
                    "WHERE datname = current_database()"
                )
            )
        ).scalar()
        _database_codec = _PYTHON_CODECS.get((name or "").upper().replace("-", "_"))
        _database_checked = True
    return _database_codec


def unsupported_characters(text: str, codec: str) -> list[str]:
    """Унікальні символи тексту, які не кодуються в `codec` (у порядку появи)."""
    bad: list[str] = []
    for char in dict.fromkeys(text):
        try:
            char.encode(codec)
        except UnicodeEncodeError:
            bad.append(char)
    return bad


_ENTITY_RE = re.compile(r"&#(\d+);")


def decode_entities(text: str) -> str:
    """Повертає справжні символи замість `&#128293;`.

    Потрібно там, де текст показується БЕЗ HTML-розмітки: підписи кнопок,
    повторне надсилання розсилки як звичайного тексту.
    """
    return _ENTITY_RE.sub(lambda match: chr(int(match.group(1))), text)


async def encode_unstorable(session: AsyncSession, text: str) -> str:
    """Замінює символи, яких база не вміщує, на числові HTML-сутності.

    Навіщо саме так: розсилку Telegram отримує з `parse_mode=HTML`, тож
    `&#128293;` показується клієнту як 🔥, а в базі WIN1251 лежить безпечний
    ASCII — INSERT більше не падає і власник може писати звичні емодзі.
    Для UTF8-бази текст повертається без змін.
    """
    codec = await database_codec(session)
    if codec is None:
        return text

    parts: list[str] = []
    for char in text:
        try:
            char.encode(codec)
        except UnicodeEncodeError:
            parts.append(f"&#{ord(char)};")  # ← працює і для ємодзі поза BMP
        else:
            parts.append(char)
    return "".join(parts)


async def storable_problem(session: AsyncSession, text: str) -> str | None:
    """Текст пояснення для користувача, якщо текст не збережеться; інакше None."""
    codec = await database_codec(session)
    if codec is None:
        return None
    bad = unsupported_characters(text, codec)
    if not bad:
        return None
    shown = " ".join(bad[:_MAX_LISTED])
    extra = f" … (ще {len(bad) - _MAX_LISTED})" if len(bad) > _MAX_LISTED else ""
    return (
        f"База не може зберегти ці символи: {shown}{extra}\n"
        "Зазвичай це емодзі або рідкісні символи — приберіть їх і надішліть ще раз."
    )


async def to_storable(session: AsyncSession, text: str) -> str:
    """Прибирає символи, які база не збереже.

    Для даних, які користувач не обирає сам (ім'я з профілю Telegram): мовчки
    обрізати краще, ніж зривати запис клієнту, який не може «перестворити» своє ім'я.
    """
    codec = await database_codec(session)
    if codec is None:
        return text
    bad = set(unsupported_characters(text, codec))
    if not bad:
        return text
    return "".join(char for char in text if char not in bad).strip()
