"""Runtime that drives an active goal across agent turns.

The :class:`GoalRuntime` is wired into the agent loop. It:

* refreshes the always-on system-prompt overlay at the start of each turn;
* accounts token/time usage at the end of each turn;
* flips the goal to ``budget_limited`` when the token budget is exhausted;
* decides whether to inject a continuation steering message so the agent
  starts another turn automatically;
* enforces a hard cap (``MAX_GOAL_TURNS``) so a goal without a budget cannot
  loop forever — a safety net Codex does not need but quiet-droid does.

The runtime holds only turn-scoped bookkeeping; durable state lives in the
:class:`~quiet_droid.goal_store.GoalStore`.
"""

import time

from . import goal_steering
from .goal_store import GoalStore


class GoalRuntime:
    MAX_GOAL_TURNS = 20

    def __init__(self, store):
        self.store = store
        self._turn_start_tokens = 0
        self._turn_start_time = 0.0
        self._goal_turn_count = 0

    # ------------------------------------------------------------------
    # turn lifecycle
    # ------------------------------------------------------------------

    def refresh_overlay(self, session_id, session):
        """Push the current goal summary into the session's system prompt."""
        goal = self.store.get_goal(session_id)
        session.set_goal_overlay(goal_steering.overlay(goal) if goal else "")
        return goal

    def begin_turn(self, session_id, session):
        """Record the start of a turn for later usage accounting."""
        goal = self.store.get_goal(session_id)
        if not goal or not goal.is_active():
            self._turn_start_tokens = 0
            self._turn_start_time = 0.0
            return
        self.refresh_overlay(session_id, session)
        self._turn_start_tokens = session.get_token_estimate()
        self._turn_start_time = time.time()

    def start_goal(self, session_id, session):
        """Prepare the runtime for a freshly activated goal.

        Resets the turn counter and records the baseline for the first
        turn. Returns True if the goal is active and ready, False
        otherwise (no goal, or inactive).
        """
        goal = self.store.get_goal(session_id)
        if not goal or not goal.is_active():
            return False
        self.reset_turn_count()
        self._goal_turn_count += 1
        self.begin_turn(session_id, session)
        return True

    def account_turn_usage(self, session_id, session, prompt_tokens=None):
        """Account for tokens/time consumed during the turn just finished."""
        goal = self.store.get_goal(session_id)
        if not goal or not goal.is_active():
            return None
        if prompt_tokens is not None and prompt_tokens > 0:
            tokens_delta = max(0, prompt_tokens - self._turn_start_tokens)
        else:
            tokens_delta = max(
                0, session.get_token_estimate() - self._turn_start_tokens
            )
        seconds_delta = max(0, time.time() - self._turn_start_time) if self._turn_start_time else 0
        return self.store.account_usage(
            session_id, tokens_delta=tokens_delta, seconds_delta=int(seconds_delta)
        )

    def check_budget(self, session_id):
        """Flip to budget_limited if the budget is exhausted.

        Returns the (possibly updated) goal, or None if there is no goal.
        """
        goal = self.store.get_goal(session_id)
        if not goal or not goal.is_active():
            return goal
        if (
            goal.token_budget is not None
            and goal.tokens_used >= goal.token_budget
        ):
            goal = self.store.update_status(session_id, "budget_limited")
        return goal

    def decide_continuation(self, session_id, goal=None):
        """Return a steering string for the next turn, or None to stop.

        Continuation is decided only for active, non-terminal goals. A hard
        turn cap protects against runaway loops when no budget is set.
        """
        if goal is None:
            goal = self.store.get_goal(session_id)
        if not goal or not goal.is_active():
            return None
        self._goal_turn_count += 1
        if self._goal_turn_count > self.MAX_GOAL_TURNS:
            return None
        return goal_steering.continuation(goal)

    def inject_continuation(self, session_id, session, goal=None):
        """Inject the continuation steering as a user message.

        Returns True if a continuation turn was started, False otherwise.
        """
        steering = self.decide_continuation(session_id, goal=goal)
        if steering is None:
            return False
        session.add_user_message(steering)
        return True

    # ------------------------------------------------------------------
    # budget-limited steering
    # ------------------------------------------------------------------

    def budget_limit_steering(self, session_id):
        goal = self.store.get_goal(session_id)
        if goal is None:
            return None
        return goal_steering.budget_limit(goal)

    # ------------------------------------------------------------------
    # status transitions
    # ------------------------------------------------------------------

    def mark_blocked(self, session_id, reason="turn_error"):
        """Transition an active goal to blocked after a fatal turn error."""
        goal = self.store.get_goal(session_id)
        if goal and goal.is_active():
            return self.store.update_status(session_id, "blocked")
        return goal

    # ------------------------------------------------------------------
    # turn-count management (for tests and reset on new goal)
    # ------------------------------------------------------------------

    def reset_turn_count(self):
        self._goal_turn_count = 0

    @property
    def goal_turn_count(self):
        return self._goal_turn_count
