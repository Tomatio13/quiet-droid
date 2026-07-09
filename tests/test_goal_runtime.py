import os
import tempfile
import unittest

from quiet_droid.goal_runtime import GoalRuntime
from quiet_droid.goal_store import GoalStore
from quiet_droid.goal_steering import overlay


class DummySession:
    """Minimal Session stand-in: tracks tokens and the goal overlay."""

    def __init__(self, session_id, tokens=0):
        self.session_id = session_id
        self._tokens = tokens
        self._goal_overlay = ""
        self.injected = []

    def get_token_estimate(self):
        return self._tokens

    def set_tokens(self, n):
        self._tokens = n

    def set_goal_overlay(self, text):
        self._goal_overlay = text or ""

    def get_goal_overlay(self):
        return self._goal_overlay

    def add_user_message(self, text):
        self.injected.append(text)


class TestGoalRuntime(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = GoalStore(os.path.join(self._tmp.name, "goals.db"))
        self.runtime = GoalRuntime(self.store)
        self.sid = "20260101_120000_abcdef"
        self.session = DummySession(self.sid, tokens=500)

    # --- refresh_overlay ---

    def test_refresh_overlay_no_goal_clears_overlay(self):
        self.session.set_goal_overlay("stale")
        goal = self.runtime.refresh_overlay(self.sid, self.session)
        self.assertIsNone(goal)
        self.assertEqual(self.session.get_goal_overlay(), "")

    def test_refresh_overlay_active_sets_overlay(self):
        self.store.replace_goal(self.sid, "ship it")
        goal = self.runtime.refresh_overlay(self.sid, self.session)
        self.assertTrue(goal.is_active())
        self.assertIn("ship it", self.session.get_goal_overlay())

    def test_refresh_overlay_inactive_goal_clears(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "paused")
        self.session.set_goal_overlay("stale")
        goal = self.runtime.refresh_overlay(self.sid, self.session)
        # paused goal -> overlay() returns "" (inactive)
        self.assertEqual(self.session.get_goal_overlay(), "")

    # --- begin_turn / account_turn_usage ---

    def test_begin_turn_records_start_baseline(self):
        self.store.replace_goal(self.sid, "x")
        self.runtime.begin_turn(self.sid, self.session)
        self.assertEqual(self.runtime._turn_start_tokens, 500)
        self.assertGreater(self.runtime._turn_start_time, 0)

    def test_begin_turn_skips_inactive_goal(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "complete")
        self.runtime.begin_turn(self.sid, self.session)
        self.assertEqual(self.runtime._turn_start_tokens, 0)
        self.assertEqual(self.runtime._turn_start_time, 0.0)

    def test_account_usage_accumulates_delta(self):
        self.store.replace_goal(self.sid, "x")
        self.runtime.begin_turn(self.sid, self.session)  # baseline 500
        self.session.set_tokens(800)
        goal = self.runtime.account_turn_usage(self.sid, self.session)
        self.assertEqual(goal.tokens_used, 300)

    def test_account_usage_with_prompt_tokens_prefers_api_value(self):
        self.store.replace_goal(self.sid, "x")
        self.runtime.begin_turn(self.sid, self.session)  # baseline 500
        goal = self.runtime.account_turn_usage(self.sid, self.session, prompt_tokens=700)
        self.assertEqual(goal.tokens_used, 200)

    def test_account_usage_skips_when_no_active_goal(self):
        goal = self.runtime.account_turn_usage(self.sid, self.session)
        self.assertIsNone(goal)

    # --- check_budget ---

    def test_check_budget_no_budget_no_change(self):
        self.store.replace_goal(self.sid, "x")
        goal = self.runtime.check_budget(self.sid)
        self.assertTrue(goal.is_active())

    def test_check_budget_under_budget_stays_active(self):
        self.store.replace_goal(self.sid, "x", token_budget=2000)
        self.store.account_usage(self.sid, tokens_delta=100, seconds_delta=0)
        goal = self.runtime.check_budget(self.sid)
        self.assertEqual(goal.status, "active")

    def test_check_budget_over_budget_flips_to_budget_limited(self):
        self.store.replace_goal(self.sid, "x", token_budget=500)
        self.store.account_usage(self.sid, tokens_delta=600, seconds_delta=0)
        goal = self.runtime.check_budget(self.sid)
        self.assertEqual(goal.status, "budget_limited")
        self.assertTrue(goal.is_terminal())

    # --- decide_continuation / inject_continuation ---

    def test_decide_continuation_active_returns_steering(self):
        self.store.replace_goal(self.sid, "x")
        steering = self.runtime.decide_continuation(self.sid)
        self.assertIsNotNone(steering)
        self.assertIn("continue", steering)

    def test_decide_continuation_inactive_returns_none(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "paused")
        self.assertIsNone(self.runtime.decide_continuation(self.sid))

    def test_decide_continuation_no_goal_returns_none(self):
        self.assertIsNone(self.runtime.decide_continuation(self.sid))

    def test_inject_continuation_adds_user_message(self):
        self.store.replace_goal(self.sid, "x")
        injected = self.runtime.inject_continuation(self.sid, self.session)
        self.assertTrue(injected)
        self.assertEqual(len(self.session.injected), 1)
        self.assertIn("continue", self.session.injected[0])

    def test_inject_continuation_skipped_for_inactive(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "complete")
        injected = self.runtime.inject_continuation(self.sid, self.session)
        self.assertFalse(injected)
        self.assertEqual(self.session.injected, [])

    def test_continuation_turn_cap_stops_looping(self):
        self.store.replace_goal(self.sid, "x")
        self.runtime.MAX_GOAL_TURNS = 2
        self.assertTrue(self.runtime.inject_continuation(self.sid, self.session))
        self.assertTrue(self.runtime.inject_continuation(self.sid, self.session))
        # third call exceeds the cap
        self.assertFalse(self.runtime.inject_continuation(self.sid, self.session))

    # --- start_goal ---

    def test_start_goal_resets_counter_and_begins_turn(self):
        self.store.replace_goal(self.sid, "x")
        # simulate a previous run that incremented the counter
        self.runtime._goal_turn_count = 5
        ok = self.runtime.start_goal(self.sid, self.session)
        self.assertTrue(ok)
        self.assertEqual(self.runtime.goal_turn_count, 1)
        self.assertEqual(self.runtime._turn_start_tokens, 500)

    def test_start_goal_no_goal_returns_false(self):
        ok = self.runtime.start_goal(self.sid, self.session)
        self.assertFalse(ok)

    def test_start_goal_inactive_returns_false(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "paused")
        ok = self.runtime.start_goal(self.sid, self.session)
        self.assertFalse(ok)

    # --- mark_blocked ---

    def test_mark_blocked_transitions_active(self):
        self.store.replace_goal(self.sid, "x")
        goal = self.runtime.mark_blocked(self.sid)
        self.assertEqual(goal.status, "blocked")

    def test_mark_blocked_noop_when_no_goal(self):
        self.assertIsNone(self.runtime.mark_blocked(self.sid))

    def test_mark_blocked_noop_when_inactive(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "complete")
        goal = self.runtime.mark_blocked(self.sid)
        self.assertEqual(goal.status, "complete")

    # --- budget_limit_steering ---

    def test_budget_limit_steering_returns_text(self):
        self.store.replace_goal(self.sid, "x")
        self.store.update_status(self.sid, "budget_limited")
        text = self.runtime.budget_limit_steering(self.sid)
        self.assertIn("budget", text.lower())

    def test_budget_limit_steering_none_when_no_goal(self):
        self.assertIsNone(self.runtime.budget_limit_steering(self.sid))


if __name__ == "__main__":
    unittest.main()
