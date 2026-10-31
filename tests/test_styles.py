import re
import unittest

from ui import styles


class StylesTests(unittest.TestCase):
    def test_token_substitution(self):
        self.assertEqual(styles.qss("color: @BLUE@;"), f"color: {styles.TOKENS['BLUE']};")
        self.assertEqual(styles.qss("color: @YOK@;"), "color: @YOK@;")  # bilinmeyen yer tutucu olduğu gibi kalır

    def test_main_qss_has_no_unresolved_tokens(self):
        text = styles.main_qss()
        self.assertFalse(re.search(r"@[A-Z0-9_]+@", text))
        self.assertEqual(text.count("{"), text.count("}"))

    def test_shared_components_present(self):
        text = styles.main_qss()
        for selector in ("QLabel#pageTitle", "QLabel#pageSubtitle", "QScrollBar:vertical", "QPushButton#dangerButton"):
            self.assertIn(selector, text)


if __name__ == "__main__":
    unittest.main()
