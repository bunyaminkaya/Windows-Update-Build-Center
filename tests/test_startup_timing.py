import logging
import unittest

from app import startup_timing as st
from services.settings_service import DEFAULT_SETTINGS


class StartupTimingTests(unittest.TestCase):
    def setUp(self):
        st.reset()

    def test_summary_lists_marks_and_slowest_pages(self):
        st.mark("Qt hazır")
        st.page_built("A", 0.010)
        st.page_built("B", 0.300)
        st.page_built("C", 0.050)
        st.mark("pencere görünür")
        text = st.summary()
        self.assertIn("Qt hazır", text)
        self.assertIn("pencere görünür", text)
        self.assertIn("en yavaş: B 300, C 50, A 10", text)

    def test_report_logs_once(self):
        st.mark("x")
        with self.assertLogs("t", level="INFO") as cap:
            st.report(logging.getLogger("t"))
            st.report(logging.getLogger("t"))
        self.assertEqual(len(cap.records), 1)

    def test_slow_start_is_warning(self):
        st._marks.append(("yavaş", 6500.0))
        with self.assertLogs("t", level="WARNING") as cap:
            st.report(logging.getLogger("t"))
        self.assertIn("Yavaş açılış", cap.output[0])

    def test_welcome_on_start_default_off(self):
        self.assertFalse(DEFAULT_SETTINGS["general"]["show_welcome_on_start"])


if __name__ == "__main__":
    unittest.main()
