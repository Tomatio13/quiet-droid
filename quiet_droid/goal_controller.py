"""Slash-command handling for /goal.

The controller parses ``/goal`` arguments and applies them against the
:class:`GoalStore`, printing human-readable feedback through the TUI. It holds
no mutable state of its own — the store (SQLite) is the single source of
truth.

Supported forms::

    /goal                       show current goal summary
    /goal <objective>           set/replace the goal objective
    /goal clear                 delete the goal
    /goal edit                  edit the objective inline
    /goal pause                 active -> paused
    /goal resume                paused -> active
    /goal budget <N>            set the token budget (positive int)
    /goal budget clear          remove the token budget
"""

from .goal_store import GoalStore, validate_objective, validate_budget
from .terminal import C, ansi


def _fmt_duration(seconds):
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _fmt_budget(goal):
    if goal.token_budget is None:
        return f"{goal.tokens_used}/∞"
    return f"{goal.tokens_used}/{goal.token_budget}"


class GoalController:
    """Handles ``/goal`` slash commands and renders summaries."""

    def __init__(self, config, tui):
        self.config = config
        self.tui = tui
        self.store = GoalStore(config.goal_db_path)

    def handle_slash(self, user_input, session_id):
        """Process a ``/goal`` command.

        Returns True when the command changes the goal into an active state
        and the agent should start/continue working on it (set, edit,
        resume). Other commands (show, clear, pause, budget) return False.
        """
        parts = user_input.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg == "":
            self._show_summary(session_id)
            return False
        if arg == "clear":
            self._clear(session_id)
            return False
        if arg == "edit":
            return self._edit(session_id)
        if arg == "pause":
            self._set_status(session_id, "paused")
            return False
        if arg == "resume":
            return self._set_status(session_id, "active")
        if arg.startswith("budget"):
            self._set_budget(session_id, arg[len("budget"):].strip())
            return False
        return self._set_objective(session_id, arg)

    # --- subcommands ----------------------------------------------------

    def _show_summary(self, session_id):
        goal = self.store.get_goal(session_id)
        if goal is None:
            print(
                f"\n  {C.DIM}No goal set. Usage: /goal <objective>{C.RESET}\n"
                f"  {C.DIM}A goal persists across turns and drives automatic "
                f"continuation until you mark it complete.{C.RESET}\n"
            )
            return
        _c51 = ansi("\033[38;5;51m")
        _c87 = ansi("\033[38;5;87m")
        print(f"\n  {_c51}━━ Goal ━━━━━━━━━━━━━━━━━━━{C.RESET}")
        print(f"  {_c87}Status{C.RESET}     {goal.status}")
        print(f"  {_c87}Objective{C.RESET}  {goal.objective}")
        print(f"  {_c87}Tokens{C.RESET}     {_fmt_budget(goal)}")
        print(f"  {_c87}Time{C.RESET}       {_fmt_duration(goal.time_used_seconds)}")
        hints = self._hints_for_status(goal.status)
        if hints:
            print(f"  {C.DIM}{hints}{C.RESET}")
        print()

    @staticmethod
    def _hints_for_status(status):
        if status == "active":
            return "Commands: /goal pause · /goal edit · /goal clear"
        if status == "paused":
            return "Commands: /goal resume · /goal edit · /goal clear"
        if status == "complete":
            return "Goal complete. /goal <new> to start another."
        if status == "blocked":
            return "Goal blocked. /goal resume to retry, /goal clear to discard."
        if status in ("usage_limited", "budget_limited"):
            return "Goal limited. /goal resume once budget is available."
        return ""

    def _set_objective(self, session_id, objective):
        existing = self.store.get_goal(session_id)
        if existing is not None and existing.is_active():
            if not self._confirm_replace(existing):
                print(f"{C.DIM}Goal unchanged.{C.RESET}")
                return False
        try:
            goal = self.store.replace_goal(session_id, objective)
        except ValueError as exc:
            print(f"{C.RED}Invalid goal: {exc}{C.RESET}")
            return False
        self._print_set_confirmation(goal, verb="set")
        return True

    def _confirm_replace(self, existing):
        print(f"{C.YELLOW}An active goal already exists:{C.RESET}")
        print(f"  {C.DIM}{existing.objective}{C.RESET}")
        return self.tui.confirm("Replace it?", default=False)

    def _clear(self, session_id):
        deleted = self.store.delete_goal(session_id)
        if deleted:
            print(f"{C.GREEN}Goal cleared.{C.RESET}")
        else:
            print(f"{C.DIM}No goal to clear.{C.RESET}")

    def _edit(self, session_id):
        existing = self.store.get_goal(session_id)
        if existing is None:
            print(f"{C.RED}No goal to edit. Set one first: /goal <objective>{C.RESET}")
            return False
        print(f"{C.DIM}Editing objective. (Enter to keep, empty line aborts.){C.RESET}")
        new_text = self.tui.get_input(prefill=existing.objective)
        if new_text is None:
            print(f"{C.DIM}Edit cancelled.{C.RESET}")
            return False
        new_text = new_text.strip()
        if not new_text:
            print(f"{C.DIM}Edit cancelled.{C.RESET}")
            return False
        if new_text == existing.objective.strip():
            print(f"{C.DIM}Objective unchanged.{C.RESET}")
            return False
        try:
            goal = self.store.update_objective(session_id, new_text)
        except ValueError as exc:
            print(f"{C.RED}Invalid objective: {exc}{C.RESET}")
            return False
        self._print_set_confirmation(goal, verb="updated")
        return True

    def _set_status(self, session_id, status):
        existing = self.store.get_goal(session_id)
        if existing is None:
            print(f"{C.RED}No goal set. Use /goal <objective> first.{C.RESET}")
            return False
        if existing.status == status:
            print(f"{C.DIM}Goal already {status}.{C.RESET}")
            return False
        self.store.update_status(session_id, status)
        label = "paused" if status == "paused" else "resumed"
        print(f"{C.GREEN}Goal {label}.{C.RESET}")
        # Only resuming an active goal should (re)kick the agent.
        return status == "active"

    def _set_budget(self, session_id, arg):
        existing = self.store.get_goal(session_id)
        if existing is None:
            print(f"{C.RED}No goal set. Use /goal <objective> first.{C.RESET}")
            return
        if arg in ("", "clear", "none", "off"):
            goal = self.store.update_budget(session_id, None)
            print(f"{C.GREEN}Token budget cleared (unlimited).{C.RESET}")
            return
        try:
            budget = validate_budget(int(arg))
        except (ValueError, TypeError):
            print(f"{C.RED}Invalid budget: {arg!r}. Use a positive integer.{C.RESET}")
            return
        if budget is None:
            print(f"{C.RED}Invalid budget: {arg!r}. Use a positive integer.{C.RESET}")
            return
        self.store.update_budget(session_id, budget)
        print(f"{C.GREEN}Token budget set to {budget}.{C.RESET}")

    # --- output helpers -------------------------------------------------

    def _print_set_confirmation(self, goal, verb):
        print(f"{C.GREEN}Goal {verb}: {goal.status}{C.RESET}")
        print(f"  {C.DIM}Objective: {goal.objective}{C.RESET}")
        usage = f"Tokens: {_fmt_budget(goal)} · Time: {_fmt_duration(goal.time_used_seconds)}"
        print(f"  {C.DIM}{usage}{C.RESET}")
