import unittest

from quiet_droid.session import Session


class DummyConfig:
    def __init__(self, context_window):
        self.context_window = context_window
        self.session_id = None
        self.model = "test-model"


class SessionContextWindowTests(unittest.TestCase):
    def test_context_window_status_is_ok_within_limit(self):
        session = Session(DummyConfig(context_window=100), "system")
        session.add_user_message("hello")

        status = session.context_window_status()

        self.assertTrue(status["ok"])
        self.assertLessEqual(status["current"], status["limit"])
        self.assertEqual(status["over_by"], 0)

    def test_context_window_status_reports_overflow(self):
        session = Session(DummyConfig(context_window=10), "system")
        session.add_user_message("x" * 80)

        status = session.context_window_status()

        self.assertFalse(status["ok"])
        self.assertGreater(status["current"], status["limit"])
        self.assertEqual(status["over_by"], status["current"] - status["limit"])
        self.assertGreater(status["pct"], 100)


if __name__ == "__main__":
    unittest.main()
