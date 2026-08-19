import sys
import unittest
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_memory.extract_openai import keep_message, scrub


class FilterTests(unittest.TestCase):
    def test_drops_short_howto(self):
        self.assertFalse(
            keep_message("Regex", "How can I match quoted strings in Python?")
        )

    def test_keeps_substantive(self):
        self.assertTrue(
            keep_message(
                "Koru fragments",
                "Don't add Tailwind to the Koru repo; fragments plus app.css tokens only.",
            )
        )

    def test_drops_long_code_dump(self):
        self.assertFalse(
            keep_message(
                "Blender Python Custom Enum",
                "def foo():\n" + "    pass\n" * 40,
            )
        )

    def test_scrubs_email(self):
        self.assertIn("[redacted]", scrub("mail me at person@example.com please"))


if __name__ == "__main__":
    unittest.main()
