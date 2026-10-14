# Tests

Швидкі тести без БД:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

Production-перевірку race condition потрібно виконувати на PostgreSQL після `alembic upgrade head`:
одночасно відправити два запити на той самий `master_id/start_at`. Міграція `0006`
встановлює PostgreSQL exclusion constraint `ex_bookings_master_time_overlap`, тому в БД
може залишитись максимум один активний запис на перетин часу одного майстра.
