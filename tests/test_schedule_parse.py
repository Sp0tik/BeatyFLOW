import unittest
from datetime import time

from app.utils.schedule_parse import ScheduleParseError, parse_working_hours_text


class ScheduleParseTests(unittest.TestCase):
    def test_split_shift_break(self):
        parsed = parse_working_hours_text(
            "Пн-Пт 09:00-13:00;14:00-18:00, Сб 10:00-15:00, Нд вихідний"
        )
        self.assertEqual(parsed[0], [(time(9), time(13)), (time(14), time(18))])
        self.assertEqual(parsed[5], [(time(10), time(15))])
        self.assertIsNone(parsed[6])

    def test_overlapping_intervals_rejected(self):
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("Пн 09:00-14:00;13:00-18:00")

    def test_reverse_weekday_range(self):
        parsed = parse_working_hours_text("Сб-Вт 10:00-12:00")
        self.assertEqual(set(parsed), {5, 6, 0, 1})

    def test_single_day_single_interval(self):
        parsed = parse_working_hours_text("Пн 09:00-18:00")
        self.assertEqual(parsed, {0: [(time(9), time(18))]})

    def test_off_word_variants(self):
        self.assertEqual(parse_working_hours_text("Нд вихідний"), {6: None})
        self.assertEqual(parse_working_hours_text("Пн off"), {0: None})

    def test_unknown_weekday_rejected(self):
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("Фб 09:00-10:00")

    def test_invalid_time_rejected(self):
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("Пн 25:00-26:00")
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("Пн 09:00")

    def test_start_not_before_end_rejected(self):
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("Пн 14:00-09:00")

    def test_empty_input_rejected(self):
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("")
        with self.assertRaises(ScheduleParseError):
            parse_working_hours_text("   ")


if __name__ == "__main__":
    unittest.main()
