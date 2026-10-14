"""Юніт-тести форматування дат/часу (app/utils/dates.py) — без БД."""

import os
import unittest
from datetime import date, datetime, timezone

os.environ.setdefault("BOT_TOKEN", "test-token-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")

from app.utils import dates as d


class DatesTests(unittest.TestCase):
    def test_format_date_human(self):
        # 2026-10-02 — п'ятниця
        self.assertEqual(d.format_date_human(date(2026, 10, 2)), "2 жовтня, Пт")

    def test_format_date_short_zero_padded(self):
        self.assertEqual(d.format_date_short(date(2026, 10, 2)), "02.10 Пт")

    def test_month_label(self):
        self.assertEqual(d.month_label(2026, 10), "Жовтень 2026")

    def test_to_local_naive_gets_salon_tz(self):
        local = d.to_local(datetime(2026, 10, 2, 12, 0))
        self.assertEqual(local.tzinfo, d.TZ)
        self.assertEqual((local.hour, local.minute), (12, 0))

    def test_to_local_aware_converts(self):
        aware_utc = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(d.to_local(aware_utc), aware_utc.astimezone(d.TZ))

    def test_format_time_matches_local(self):
        dt = datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc)
        self.assertEqual(d.format_time(dt), d.to_local(dt).strftime("%H:%M"))

    def test_format_moment_shape(self):
        text = d.format_moment(datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc))
        self.assertIn(" о ", text)


if __name__ == "__main__":
    unittest.main()
