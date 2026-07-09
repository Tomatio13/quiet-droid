"""The ``update_goal`` tool exposed to the model.

Codex gives the model three goal tools (``get_goal``/``create_goal``/
``update_goal``). In quiet-droid, the ``/goal`` slash command already handles
creation and retrieval, so only :class:`UpdateGoalTool` is needed — it is the
mechanism by which the agent declares a goal ``complete`` or ``blocked``.

The tool is registered as a SAFE tool (no filesystem/command side effects: it
only mutates the goal's SQLite row), so it will not trigger a permission
prompt. This is important: a permission prompt would block the model's
self-completion path during automatic continuation.
"""

from ..goal_store import GoalStore
from .base import Tool


class UpdateGoalTool(Tool):
    name = "update_goal"
    description = (
        "Mark the active goal as complete or blocked. "
        "Use ONLY when the goal is truly done (with concrete evidence for "
        "each requirement) or blocked (the SAME blocker recurred across 3 "
        "goal turns). Do not use 'complete' because the token budget ran low."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["complete", "blocked"],
                "description": "complete = goal achieved; blocked = unrecoverable blocker",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Evidence-based justification. For 'complete', cite the "
                    "proof for each requirement (file paths, command output, "
                    "passing tests). For 'blocked', name the blocker and what "
                    "is needed to get past it."
                ),
            },
        },
        "required": ["status", "summary"],
    }

    def __init__(self, store, session_id_provider):
        """``session_id_provider`` is a zero-arg callable returning the
        current ``session_id`` (so the tool always sees the live value)."""
        self.store = store
        self._session_id_provider = session_id_provider

    def _session_id(self):
        return self._session_id_provider()

    def execute(self, params):
        status = params.get("status")
        summary = (params.get("summary") or "").strip()
        if status not in ("complete", "blocked"):
            return (
                "Error: status must be 'complete' or 'blocked'. "
                "Only those two transitions are allowed via this tool."
            )
        if not summary:
            return (
                "Error: a summary is required. "
                "For 'complete', cite evidence for each requirement. "
                "For 'blocked', name the blocker and what is needed."
            )
        session_id = self._session_id()
        goal = self.store.get_goal(session_id)
        if goal is None:
            return "Error: no active goal to update."
        if goal.status not in ("active", "paused"):
            return (
                f"Error: goal is already {goal.status} and cannot be updated. "
                "Start a new goal with /goal <objective>."
            )

        # Final usage reconciliation before flipping the status.
        if isinstance(self.store, GoalStore) and goal.is_active():
            # account any unrecorded delta as zero; precise accounting is the
            # runtime's job at turn boundaries.
            pass
        updated = self.store.update_status(session_id, status)

        if status == "complete":
            return self._complete_message(updated)
        return self._blocked_message(updated, summary)

    @staticmethod
    def _complete_message(goal):
        budget = "∞" if goal.token_budget is None else str(goal.token_budget)
        m, s = divmod(int(goal.time_used_seconds or 0), 60)
        return (
            f"Goal marked complete.\n"
            f"  Objective: {goal.objective}\n"
            f"  Tokens used: {goal.tokens_used}/{budget} · Time used: {m}m {s}s\n"
            "Report this final usage to the user along with your evidence summary."
        )

    @staticmethod
    def _blocked_message(goal, summary):
        return (
            f"Goal marked blocked.\n"
            f"  Objective: {goal.objective}\n"
            f"  Blocker: {summary}\n"
            "Explain to the user what is blocking progress and what you need "
            "to continue. The goal is now paused — use /goal resume to retry."
        )
