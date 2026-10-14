"""Юніт-тести чистих функцій app/utils/db_text.py — без БД."""

import unittest

from app.utils.db_text import decode_entities, unsupported_characters


class DbTextTests(unittest.TestCase):
    def test_decode_single_entity(self):
        self.assertEqual(decode_entities("Fire: &#128293;"), "Fire: 🔥")

    def test_decode_leaves_plain_text(self):
        self.assertEqual(decode_entities("Манікюр 500₴"), "Манікюр 500₴")

    def test_decode_multiple_entities(self):
        self.assertEqual(decode_entities("&#128077;&#127995; ok"), "👍🏻 ok")

    def test_unsupported_finds_emoji_for_cp1251(self):
        self.assertEqual(unsupported_characters("Акція 🔥", "cp1251"), ["🔥"])

    def test_unsupported_empty_for_cyrillic_cp1251(self):
        self.assertEqual(unsupported_characters("Манікюр класичний", "cp1251"), [])

    def test_unsupported_dedupes_in_order(self):
        self.assertEqual(unsupported_characters("🔥a🔥b🔥", "cp1251"), ["🔥"])


if __name__ == "__main__":
    unittest.main()
