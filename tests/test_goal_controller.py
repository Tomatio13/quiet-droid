import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from quiet_droid.goal_controller import GoalController, _fmt_duration, _fmt_budget
from quiet_droid.goal_store import GoalStore, Goal


class DummyConfig:
    def __init__(self, tmpdir):
        self.goal_db_path = os.path.join(tmpdir, "goals.db")


class DummyTUI:
    """Captures get_input/confirm return values to simulate user interaction."""

    def __init__(self, input_value="", confirm_value=False):
        self._input_value = input_value
        self._confirm_value = confirm_value

    def get_input(self, prefill=""):
        return self._input_value

    def confirm(self, prompt, default=False):
        return self._confirm_value


class TestGoalController(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = DummyConfig(self._tmp.name)
        self.tui = DummyTUI()
        self.controller = GoalController(self.config, self.tui)
        self.sid = "20260101_120000_abcdef"

    def _out(self, fn):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def _out_with_result(self, fn):
        """Run fn (which returns a value), capturing stdout.

        Returns (output_text, return_value).
        """
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn()
        return buf.getvalue(), result

    # --- argument dispatch ---

    def test_summary_no_goal_shows_usage(self):
        result = self._out_with_result(lambda: self.controller.handle_slash("/goal", self.sid))
        out, should_run = result
        self.assertIn("No goal set", out)
        self.assertIn("/goal <objective>", out)
        self.assertFalse(should_run)

    def test_summary_with_goal_shows_fields(self):
        self.controller.store.replace_goal(self.sid, "ship the feature", token_budget=2000)
        self.controller.store.account_usage(self.sid, tokens_delta=300, seconds_delta=75)
        out = self._out(lambda: self.controller.handle_slash("/goal", self.sid))
        self.assertIn("active", out)
        self.assertIn("ship the feature", out)
        self.assertIn("300/2000", out)
        self.assertIn("1m 15s", out)

    def test_set_objective_creates_goal(self):
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal refactor everything", self.sid)
        )
        goal = self.controller.store.get_goal(self.sid)
        self.assertEqual(goal.objective, "refactor everything")
        self.assertEqual(goal.status, "active")
        self.assertIn("Goal set", out)
        self.assertTrue(should_run)

    def test_set_objective_replace_active_without_confirm(self):
        self.controller.store.replace_goal(self.sid, "first")
        self.tui._confirm_value = False
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal second", self.sid)
        )
        self.assertIn("Goal unchanged", out)
        self.assertEqual(self.controller.store.get_goal(self.sid).objective, "first")
        self.assertFalse(should_run)

    def test_set_objective_replace_active_with_confirm(self):
        self.controller.store.replace_goal(self.sid, "first")
        self.tui._confirm_value = True
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal second", self.sid)
        )
        self.assertEqual(self.controller.store.get_goal(self.sid).objective, "second")
        self.assertIn("Goal set", out)
        self.assertTrue(should_run)

    def test_set_objective_invalid_shows_error(self):
        out = self._out(lambda: self.controller.handle_slash("/goal    ", self.sid))
        # all-whitespace => empty arg => falls to summary, not set
        self.assertIn("No goal set", out)

    def test_clear_when_present(self):
        self.controller.store.replace_goal(self.sid, "obj")
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal clear", self.sid)
        )
        self.assertIn("Goal cleared", out)
        self.assertIsNone(self.controller.store.get_goal(self.sid))
        self.assertFalse(should_run)

    def test_clear_when_absent(self):
        out = self._out(lambda: self.controller.handle_slash("/goal clear", self.sid))
        self.assertIn("No goal to clear", out)

    def test_edit_no_goal(self):
        out = self._out(lambda: self.controller.handle_slash("/goal edit", self.sid))
        self.assertIn("No goal to edit", out)

    def test_edit_unchanged(self):
        self.controller.store.replace_goal(self.sid, "original")
        self.tui._input_value = "original"
        out = self._out(lambda: self.controller.handle_slash("/goal edit", self.sid))
        self.assertIn("Objective unchanged", out)

    def test_edit_cancelled_on_empty(self):
        self.controller.store.replace_goal(self.sid, "original")
        self.tui._input_value = ""
        out = self._out(lambda: self.controller.handle_slash("/goal edit", self.sid))
        self.assertIn("cancelled", out)

    def test_edit_success(self):
        self.controller.store.replace_goal(self.sid, "original")
        self.tui._input_value = "revised objective"
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal edit", self.sid)
        )
        self.assertEqual(self.controller.store.get_goal(self.sid).objective, "revised objective")
        self.assertIn("Goal updated", out)
        self.assertTrue(should_run)

    def test_edit_cancelled_returns_false(self):
        self.controller.store.replace_goal(self.sid, "original")
        self.tui._input_value = ""
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal edit", self.sid)
        )
        self.assertIn("cancelled", out)
        self.assertFalse(should_run)

    def test_pause_and_resume(self):
        self.controller.store.replace_goal(self.sid, "obj")
        out_pause, run_pause = self._out_with_result(
            lambda: self.controller.handle_slash("/goal pause", self.sid)
        )
        self.assertIn("Goal paused", out_pause)
        self.assertEqual(self.controller.store.get_goal(self.sid).status, "paused")
        self.assertFalse(run_pause)
        out_resume, run_resume = self._out_with_result(
            lambda: self.controller.handle_slash("/goal resume", self.sid)
        )
        self.assertIn("Goal resumed", out_resume)
        self.assertEqual(self.controller.store.get_goal(self.sid).status, "active")
        self.assertTrue(run_resume)

    def test_pause_no_goal(self):
        out = self._out(lambda: self.controller.handle_slash("/goal pause", self.sid))
        self.assertIn("No goal set", out)

    def test_pause_idempotent(self):
        self.controller.store.replace_goal(self.sid, "obj")
        self.controller.store.update_status(self.sid, "paused")
        out = self._out(lambda: self.controller.handle_slash("/goal pause", self.sid))
        self.assertIn("already paused", out)

    def test_budget_set(self):
        self.controller.store.replace_goal(self.sid, "obj")
        out, should_run = self._out_with_result(
            lambda: self.controller.handle_slash("/goal budget 5000", self.sid)
        )
        self.assertIn("Token budget set to 5000", out)
        self.assertEqual(self.controller.store.get_goal(self.sid).token_budget, 5000)
        self.assertFalse(should_run)

    def test_budget_clear(self):
        self.controller.store.replace_goal(self.sid, "obj", token_budget=1000)
        out = self._out(lambda: self.controller.handle_slash("/goal budget clear", self.sid))
        self.assertIn("budget cleared", out)
        self.assertIsNone(self.controller.store.get_goal(self.sid).token_budget)

    def test_budget_invalid(self):
        self.controller.store.replace_goal(self.sid, "obj")
        out = self._out(lambda: self.controller.handle_slash("/goal budget abc", self.sid))
        self.assertIn("Invalid budget", out)
        out = self._out(lambda: self.controller.handle_slash("/goal budget -5", self.sid))
        self.assertIn("Invalid budget", out)

    def test_budget_no_goal(self):
        out = self._out(lambda: self.controller.handle_slash("/goal budget 100", self.sid))
        self.assertIn("No goal set", out)


class TestFormatHelpers(unittest.TestCase):
    def test_fmt_duration(self):
        self.assertEqual(_fmt_duration(0), "0s")
        self.assertEqual(_fmt_duration(45), "45s")
        self.assertEqual(_fmt_duration(75), "1m 15s")
        self.assertEqual(_fmt_duration(3661), "1h 1m 1s")

    def test_fmt_budget_unlimited(self):
        goal = Goal(tokens_used=120, token_budget=None)
        self.assertEqual(_fmt_budget(goal), "120/∞")

    def test_fmt_budget_limited(self):
        goal = Goal(tokens_used=120, token_budget=1000)
        self.assertEqual(_fmt_budget(goal), "120/1000")


if __name__ == "__main__":
    unittest.main()
