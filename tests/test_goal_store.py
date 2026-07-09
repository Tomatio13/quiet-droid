import os
import tempfile
import unittest

from quiet_droid.goal_store import (
    GoalStore,
    Goal,
    MAX_OBJECTIVE_CHARS,
    validate_objective,
    validate_budget,
)


class TestValidation(unittest.TestCase):
    def test_validate_objective_trims_and_accepts(self):
        self.assertEqual(validate_objective("  hello  "), "hello")

    def test_validate_objective_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_objective("   ")
        with self.assertRaises(ValueError):
            validate_objective("")

    def test_validate_objective_rejects_too_long(self):
        with self.assertRaises(ValueError):
            validate_objective("x" * (MAX_OBJECTIVE_CHARS + 1))

    def test_validate_objective_rejects_non_string(self):
        with self.assertRaises(ValueError):
            validate_objective(123)

    def test_validate_budget_none(self):
        self.assertIsNone(validate_budget(None))

    def test_validate_budget_positive(self):
        self.assertEqual(validate_budget(1000), 1000)
        self.assertEqual(validate_budget("500"), 500)

    def test_validate_budget_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            validate_budget(0)
        with self.assertRaises(ValueError):
            validate_budget(-10)

    def test_validate_budget_rejects_non_int(self):
        with self.assertRaises(ValueError):
            validate_budget("abc")


class TestGoalStoreCRUD(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "goals.db")
        self.store = GoalStore(self.db_path)
        self.sid = "20260101_120000_abcdef"

    def test_get_goal_returns_none_when_absent(self):
        self.assertIsNone(self.store.get_goal(self.sid))

    def test_replace_goal_creates_active_goal(self):
        goal = self.store.replace_goal(self.sid, "refactor the parser", token_budget=2000)
        self.assertIsInstance(goal, Goal)
        self.assertEqual(goal.session_id, self.sid)
        self.assertEqual(goal.objective, "refactor the parser")
        self.assertEqual(goal.status, "active")
        self.assertEqual(goal.token_budget, 2000)
        self.assertEqual(goal.tokens_used, 0)
        self.assertEqual(goal.time_used_seconds, 0)
        self.assertTrue(goal.goal_id)
        self.assertTrue(goal.is_active())
        self.assertFalse(goal.is_terminal())

    def test_replace_goal_overwrites_existing(self):
        self.store.replace_goal(self.sid, "first objective")
        new = self.store.replace_goal(self.sid, "second objective", token_budget=100)
        self.assertEqual(new.objective, "second objective")
        self.assertEqual(new.token_budget, 100)
        self.assertEqual(new.tokens_used, 0)
        self.assertNotEqual(
            new.goal_id,
            self.store.replace_goal(self.sid, "x").goal_id,
        )

    def test_replace_goal_rejects_invalid_objective(self):
        with self.assertRaises(ValueError):
            self.store.replace_goal(self.sid, "  ")

    def test_get_goal_roundtrips(self):
        self.store.replace_goal(self.sid, "write tests")
        fetched = self.store.get_goal(self.sid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.objective, "write tests")

    def test_update_status(self):
        self.store.replace_goal(self.sid, "obj")
        updated = self.store.update_status(self.sid, "paused")
        self.assertEqual(updated.status, "paused")
        self.assertFalse(updated.is_active())
        self.store.update_status(self.sid, "complete")
        self.assertTrue(self.store.get_goal(self.sid).is_terminal())

    def test_update_status_rejects_unknown(self):
        self.store.replace_goal(self.sid, "obj")
        with self.assertRaises(ValueError):
            self.store.update_status(self.sid, "flying")

    def test_update_status_returns_none_when_absent(self):
        self.assertIsNone(self.store.update_status("missing", "paused"))

    def test_update_objective(self):
        self.store.replace_goal(self.sid, "old")
        updated = self.store.update_objective(self.sid, "new objective")
        self.assertEqual(updated.objective, "new objective")
        self.assertEqual(self.store.get_goal(self.sid).objective, "new objective")

    def test_update_objective_rejects_empty(self):
        self.store.replace_goal(self.sid, "old")
        with self.assertRaises(ValueError):
            self.store.update_objective(self.sid, "")

    def test_update_objective_returns_none_when_absent(self):
        self.assertIsNone(self.store.update_objective("missing", "x"))

    def test_update_budget(self):
        self.store.replace_goal(self.sid, "obj")
        updated = self.store.update_budget(self.sid, 5000)
        self.assertEqual(updated.token_budget, 5000)
        # Setting to None clears the budget.
        cleared = self.store.update_budget(self.sid, None)
        self.assertIsNone(cleared.token_budget)

    def test_update_budget_rejects_non_positive(self):
        self.store.replace_goal(self.sid, "obj")
        with self.assertRaises(ValueError):
            self.store.update_budget(self.sid, 0)

    def test_update_budget_returns_none_when_absent(self):
        self.assertIsNone(self.store.update_budget("missing", 100))

    def test_account_usage_accumulates(self):
        self.store.replace_goal(self.sid, "obj")
        self.store.account_usage(self.sid, tokens_delta=100, seconds_delta=30)
        after = self.store.account_usage(self.sid, tokens_delta=50, seconds_delta=10)
        self.assertEqual(after.tokens_used, 150)
        self.assertEqual(after.time_used_seconds, 40)

    def test_account_usage_returns_none_when_absent(self):
        self.assertIsNone(
            self.store.account_usage("missing", tokens_delta=1, seconds_delta=1)
        )

    def test_delete_goal(self):
        self.store.replace_goal(self.sid, "obj")
        self.assertTrue(self.store.delete_goal(self.sid))
        self.assertIsNone(self.store.get_goal(self.sid))
        self.assertFalse(self.store.delete_goal(self.sid))

    def test_created_and_updated_ms_advance(self):
        self.store.replace_goal(self.sid, "obj")
        before = self.store.get_goal(self.sid)
        self.assertEqual(before.created_at_ms, before.updated_at_ms)
        self.store.update_status(self.sid, "paused")
        after = self.store.get_goal(self.sid)
        self.assertEqual(after.created_at_ms, before.created_at_ms)
        self.assertGreaterEqual(after.updated_at_ms, before.updated_at_ms)

    def test_schema_is_idempotent(self):
        # Re-opening the store on the same db must not error.
        store2 = GoalStore(self.db_path)
        store2.replace_goal(self.sid, "obj again")
        self.assertEqual(store2.get_goal(self.sid).objective, "obj again")


if __name__ == "__main__":
    unittest.main()
