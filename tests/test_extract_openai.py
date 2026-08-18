import unittest

from extract_openai import keep_message, scrub


class FilterTests(unittest.TestCase):
    def test_drops_howto_without_signal(self):
        self.assertFalse(
            keep_message("Regex for Quoted Strings", "How can I match quoted strings in Python?")
        )

    def test_keeps_signal(self):
        self.assertTrue(
            keep_message(
                "Koru fragments",
                "Don't add Tailwind to the Koru repo; fragments plus app.css tokens only.",
            )
        )

    def test_drops_blender_howto(self):
        self.assertFalse(
            keep_message(
                "Blender Python Custom Enum",
                "In Blender Python, how can I use template_ID for a custom enum",
            )
        )

    def test_scrubs_email(self):
        self.assertIn("[redacted]", scrub("mail me at person@example.com please"))


if __name__ == "__main__":
    unittest.main()
