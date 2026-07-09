"""Steering prompts injected into the conversation to drive an active goal.

Three variants mirror Codex's ``ext/goal/templates/goals/*.md``:

* :func:`continuation` — injected on an idle goal turn to make concrete progress.
* :func:`objective_updated` — injected after ``/goal edit`` changes the objective.
* :func:`budget_limit` — injected when the token budget is exhausted.

Each function takes a :class:`~quiet_droid.goal_store.Goal` snapshot and returns
a plain-text string suitable for a ``user`` message. They are pure functions,
which makes them straightforward to unit-test.
"""

from .goal_store import Goal

USAGE_LINE = "Tokens used: {used}/{budget} · Time used: {time}"


def _usage_line(goal):
    budget = "∞" if goal.token_budget is None else str(goal.token_budget)
    m, s = divmod(int(goal.time_used_seconds or 0), 60)
    return USAGE_LINE.format(used=goal.tokens_used, budget=budget, time=f"{m}m {s}s")


def _header(goal, kind):
    return (
        f"[Goal steering — {kind}]\n"
        f"Objective: {goal.objective}\n"
        f"Status: {goal.status}\n"
        f"{_usage_line(goal)}\n"
    )


def continuation(goal):
    """Steering for an idle goal turn: make concrete progress or finish.

    Enforces a strict completion audit: the goal may only be marked complete
    once every requirement is backed by evidence, and blocked is only allowed
    when the same blocker recurred across 3 consecutive goal turns.
    """
    if not isinstance(goal, Goal):
        raise TypeError("continuation() requires a Goal")
    return (
        _header(goal, "continue")
        + """
Continue working toward this goal. Pick the next concrete sub-step that was
not yet done and DO it with a tool — do not summarize or ask for permission
unless genuinely blocked.

When you believe the goal is complete:
- Verify EACH requirement with concrete evidence (file paths, command output,
  passing tests). Do not declare success from a plan or an intention.
- If evidence is missing or weak, keep working instead of declaring complete.
- Do NOT mark the goal complete merely because the token budget is running low.
- Then call the update_goal tool with status "complete" and a summary of the
  evidence, and report the final token usage to the user.

Only if the SAME blocker has recurred across 3 consecutive goal turns:
- Call the update_goal tool with status "blocked" and explain the blocker and
  what you would need to get past it.
"""
    )


def objective_updated(goal, old_objective):
    """Steering after ``/goal edit`` changed the objective."""
    if not isinstance(goal, Goal):
        raise TypeError("objective_updated() requires a Goal")
    return (
        _header(goal, "objective updated")
        + f"""
The goal objective was updated.
Previous objective: {old_objective or '(none)'}
New objective: {goal.objective}

Realign your work to the NEW objective. Earlier progress that no longer
applies can be discarded. Continue with the next concrete step.
"""
    )


def budget_limit(goal):
    """Steering when the token budget is exhausted."""
    if not isinstance(goal, Goal):
        raise TypeError("budget_limit() requires a Goal")
    return (
        _header(goal, "budget exhausted")
        + """
The token budget for this goal has been reached. Automatic continuation is
now stopped.

Do NOT mark the goal complete just because the budget ran out. Summarize the
current state for the user: what is done, what remains, and what you would do
next. Let the user decide whether to raise the budget (/goal budget <N>),
pause (/goal pause), or clear the goal (/goal clear).
"""
    )


def overlay(goal):
    """The always-on summary appended to the system prompt for an active goal.

    Returns an empty string when ``goal`` is falsy (no goal / inactive), so
    callers can assign the result directly to ``session.set_goal_overlay``.
    """
    if not goal or not goal.is_active():
        return ""
    budget = "∞" if goal.token_budget is None else str(goal.token_budget)
    m, s = divmod(int(goal.time_used_seconds or 0), 60)
    return (
        "# Active Goal\n"
        f"Objective: {goal.objective}\n"
        f"Status: {goal.status} | Tokens: {goal.tokens_used}/{budget} | "
        f"Time: {m}m {s}s\n"
        "Pursue this goal across turns. Use the update_goal tool to mark it "
        "complete (with evidence) or blocked (only if the same blocker "
        "recurred across 3 goal turns). Do not declare complete without "
        "evidence, and do not declare complete because of a budget limit."
    )
