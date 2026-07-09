import unittest

from quiet_droid.goal_steering import (
    continuation,
    objective_updated,
    budget_limit,
    overlay,
)
from quiet_droid.goal_store import Goal


def _make_goal(**kw):
    defaults = dict(
        session_id="s1",
        goal_id="g1",
        objective="ship the feature",
        status="active",
        token_budget=2000,
        tokens_used=300,
        time_used_seconds=75,
        created_at_ms=0,
        updated_at_ms=0,
    )
    defaults.update(kw)
    return Goal(**defaults)


class TestContinuation(unittest.TestCase):
    def test_contains_objective_and_status(self):
        text = continuation(_make_goal())
        self.assertIn("ship the feature", text)
        self.assertIn("active", text)
        self.assertIn("[Goal steering — continue]", text)

    def test_includes_usage(self):
        text = continuation(_make_goal(tokens_used=300, token_budget=2000))
        self.assertIn("300/2000", text)
        self.assertIn("1m 15s", text)

    def test_includes_completion_audit_rules(self):
        text = continuation(_make_goal())
        self.assertIn("complete", text)
        self.assertIn("evidence", text)
        self.assertIn("blocked", text)
        self.assertIn("update_goal", text)

    def test_includes_budget_guard(self):
        text = continuation(_make_goal())
        self.assertIn("budget", text.lower())

    def test_rejects_non_goal(self):
        with self.assertRaises(TypeError):
            continuation("not a goal")


class TestObjectiveUpdated(unittest.TestCase):
    def test_shows_old_and_new(self):
        goal = _make_goal(objective="new objective")
        text = objective_updated(goal, old_objective="old objective")
        self.assertIn("old objective", text)
        self.assertIn("new objective", text)
        self.assertIn("[Goal steering — objective updated]", text)

    def test_old_none_shows_placeholder(self):
        goal = _make_goal(objective="only new")
        text = objective_updated(goal, old_objective="")
        self.assertIn("(none)", text)


class TestBudgetLimit(unittest.TestCase):
    def test_contains_budget_language(self):
        text = budget_limit(_make_goal(status="budget_limited"))
        self.assertIn("budget", text.lower())
        self.assertIn("[Goal steering — budget exhausted]", text)
        self.assertIn("stopped", text)

    def test_forbids_completing_on_budget(self):
        text = budget_limit(_make_goal())
        self.assertIn("Do NOT mark the goal complete", text)


class TestOverlay(unittest.TestCase):
    def test_active_goal_produces_overlay(self):
        text = overlay(_make_goal())
        self.assertIn("# Active Goal", text)
        self.assertIn("ship the feature", text)
        self.assertIn("300/2000", text)
        self.assertIn("update_goal", text)

    def test_unlimited_budget_shows_infinity(self):
        text = overlay(_make_goal(token_budget=None, tokens_used=10))
        self.assertIn("10/∞", text)

    def test_inactive_goal_returns_empty(self):
        self.assertEqual("", overlay(_make_goal(status="paused")))
        self.assertEqual("", overlay(_make_goal(status="complete")))

    def test_no_goal_returns_empty(self):
        self.assertEqual("", overlay(None))


if __name__ == "__main__":
    unittest.main()
