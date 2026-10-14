from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": у .env лежать ще POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB
    # (потрібні docker-compose для сервіса db), які не належать до Settings.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/dbname
    redis_url: str = "redis://redis:6379/0"

    # Часовий пояс салону (для генерації слотів і нагадувань)
    timezone: str = "Europe/Kyiv"

    # За скільки годин до запису надсилати нагадування
    reminder_hours_before: int = 3

    # Вікно (локальний час салону), у якому дозволені автоматичні розсилки
    # [start; end) — щоб не писати клієнтам вночі.
    broadcast_hour_start: int = 10
    broadcast_hour_end: int = 19

    # Скільки днів вперед клієнт може бачити для запису
    booking_horizon_days: int = 14

    # Крок слоту в хвилинах (гранулярність сітки часу)
    slot_step_minutes: int = 15

    # Додатковий буфер після кожної послуги (прибирання / підготовка).
    # 0 зберігає поточну поведінку. За потреби можна задати глобально через .env.
    default_buffer_minutes: int = 0

    # Нагадування забираються із запасом назад, щоб перезапуск контейнера або
    # короткий простій не призвів до пропущеного повідомлення.
    reminder_catchup_minutes: int = 30

    # Telegram tg_id власника салону — отримує розширене меню для керування майстрами,
    # послугами та сповіщення про збої бота. Дізнатись свій tg_id можна через @userinfobot.
    owner_tg_id: int | None = None


settings = Settings()
