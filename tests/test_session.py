import os
import tempfile
import unittest

from quiet_droid.session import Session


class DummyConfig:
    def __init__(self, context_window, root=None):
        self.context_window = context_window
        self.session_id = None
        self.model = "test-model"
        self.cwd = root or os.getcwd()
        self.sessions_dir = root or os.getcwd()


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

    def test_save_and_load_restores_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.add_droid_message("done")
            session.save()

            restored = Session(config, "system")
            self.assertTrue(restored.load(session.session_id))

        self.assertEqual([m["role"] for m in restored.messages], ["user", "assistant"])
        self.assertEqual(restored.messages[0]["content"], "hello")
        self.assertEqual(restored.messages[1]["content"], "done")

    def test_save_updates_project_session_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.save()

            self.assertEqual(Session.get_project_session(config), session.session_id)

    def test_list_sessions_returns_saved_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.save()

            sessions = Session.list_sessions(config)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], session.session_id)


if __name__ == "__main__":
    unittest.main()
