import os
import tempfile
import unittest

from quiet_droid.goal_store import GoalStore
from quiet_droid.tools.goal_tool import UpdateGoalTool


class TestUpdateGoalTool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = GoalStore(os.path.join(self._tmp.name, "goals.db"))
        self.sid = "20260101_120000_abcdef"
        self.tool = UpdateGoalTool(self.store, lambda: self.sid)

    def _seed(self, status="active", **kw):
        self.store.replace_goal(self.sid, kw.pop("objective", "ship it"), **kw)
        if status != "active":
            self.store.update_status(self.sid, status)

    # --- schema ---

    def test_schema_has_required_fields(self):
        schema = self.tool.get_schema()
        self.assertEqual(schema["function"]["name"], "update_goal")
        props = schema["function"]["parameters"]["properties"]
        self.assertIn("status", props)
        self.assertIn("summary", props)
        self.assertEqual(
            set(schema["function"]["parameters"]["required"]),
            {"status", "summary"},
        )
        self.assertEqual(
            set(props["status"]["enum"]), {"complete", "blocked"}
        )

    # --- validation ---

    def test_rejects_invalid_status(self):
        self._seed()
        out = self.tool.execute({"status": "flying", "summary": "x"})
        self.assertTrue(out.startswith("Error:"))

    def test_rejects_missing_summary(self):
        self._seed()
        out = self.tool.execute({"status": "complete", "summary": "  "})
        self.assertTrue(out.startswith("Error:"))
        self.assertIn("summary", out)

    def test_rejects_when_no_goal(self):
        out = self.tool.execute({"status": "complete", "summary": "done"})
        self.assertTrue(out.startswith("Error: no active goal"))

    def test_rejects_when_already_terminal(self):
        self._seed(status="complete")
        out = self.tool.execute({"status": "complete", "summary": "x"})
        self.assertTrue(out.startswith("Error:"))
        self.assertIn("already complete", out)

    def test_rejects_when_budget_limited(self):
        self._seed(status="budget_limited")
        out = self.tool.execute({"status": "complete", "summary": "x"})
        self.assertTrue(out.startswith("Error:"))
        self.assertIn("already budget_limited", out)

    # --- complete ---

    def test_complete_transitions_and_reports_usage(self):
        self._seed(token_budget=2000)
        self.store.account_usage(self.sid, tokens_delta=450, seconds_delta=95)
        out = self.tool.execute({"status": "complete", "summary": "all tests pass"})
        goal = self.store.get_goal(self.sid)
        self.assertEqual(goal.status, "complete")
        self.assertIn("Goal marked complete", out)
        self.assertIn("450/2000", out)
        self.assertIn("1m 35s", out)
        self.assertIn("Report this final usage", out)

    def test_complete_unlimited_budget(self):
        self._seed(token_budget=None)
        out = self.tool.execute({"status": "complete", "summary": "done"})
        self.assertIn("/∞", out)

    # --- blocked ---

    def test_blocked_transitions(self):
        self._seed()
        out = self.tool.execute(
            {"status": "blocked", "summary": "missing API credentials"}
        )
        goal = self.store.get_goal(self.sid)
        self.assertEqual(goal.status, "blocked")
        self.assertIn("Goal marked blocked", out)
        self.assertIn("missing API credentials", out)

    def test_blocked_from_paused_goal(self):
        # A paused goal may still be declared blocked via the tool.
        self._seed(status="paused")
        out = self.tool.execute({"status": "blocked", "summary": "stuck"})
        goal = self.store.get_goal(self.sid)
        self.assertEqual(goal.status, "blocked")
        self.assertFalse(out.startswith("Error"))


class TestSessionIdProvider(unittest.TestCase):
    def test_provider_is_called_lazily(self):
        calls = []

        def provider():
            calls.append(True)
            return "live-sid"

        store = GoalStore(tempfile.mkdtemp() + "/g.db")
        tool = UpdateGoalTool(store, provider)
        tool.execute({"status": "complete", "summary": "x"})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
