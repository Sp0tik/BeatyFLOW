import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionSecurityTests(unittest.TestCase):
    def test_real_env_is_not_shipped(self):
        self.assertFalse((ROOT / ".env").exists())

    def test_example_has_no_telegram_token(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", text))

    def test_gitignore_blocks_env(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", text)


if __name__ == "__main__":
    unittest.main()
