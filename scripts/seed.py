"""
ОПЦІЙНО: більше не обов'язково для запуску. Власник тепер може додати майстра і послуги
прямо через бота (кнопки «⚙️ Керування майстрами» та «🧾 Послуги та ціни» в /start).

Цей скрипт лишається як швидкий спосіб наповнити тестову БД під час розробки.
Запуск: python -m scripts.seed
"""
import asyncio
import secrets
from datetime import time

from app.database import async_session
from app.models import Master, MasterService, Service, WorkingHours


async def seed() -> None:
    async with async_session() as session:
        auth_code = secrets.token_hex(4)
        master = Master(full_name="Олена", tg_id=None, auth_code=auth_code, is_active=True)
        session.add(master)
        await session.flush()

        for weekday in range(0, 5):  # Пн-Пт, 9:00-18:00
            session.add(
                WorkingHours(master_id=master.id, weekday=weekday, start_time=time(9, 0), end_time=time(18, 0))
            )

        services_data = [
            ("Манікюр класичний", 60, 350),
            ("Манікюр апаратний", 75, 450),
            ("Покриття гель-лак", 90, 500),
            ("Педикюр класичний", 90, 500),
        ]
        for name, duration, price in services_data:
            service = Service(name=name)
            session.add(service)
            await session.flush()
            session.add(
                MasterService(master_id=master.id, service_id=service.id, duration_min=duration, price=price)
            )

        await session.commit()
        print(f"Створено майстра '{master.full_name}' (id={master.id}) з {len(services_data)} послугами.")
        print(f"Код авторизації для майстра: {auth_code}")
        print(f"Майстер має написати боту: /master {auth_code}")


if __name__ == "__main__":
    asyncio.run(seed())
