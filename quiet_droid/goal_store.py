"""Persistent goal storage for /goal.

A goal is a long-running task objective that is persisted across turns (and
across session resume) in a per-project SQLite database. The schema mirrors
Codex's ``thread_goals`` table so the semantics stay aligned.

The store is intentionally small: each method opens a short-lived connection,
performs a single transaction, and returns a :class:`Goal` snapshot (or
``None``). Callers never hold a connection across turns, which keeps us free
of threading concerns.
"""

import sqlite3
import time
import uuid

GOAL_STATUSES = (
    "active",
    "paused",
    "blocked",
    "usage_limited",
    "budget_limited",
    "complete",
)
MAX_OBJECTIVE_CHARS = 4000

SCHEMA = """
CREATE TABLE IF NOT EXISTS thread_goals (
    session_id        TEXT PRIMARY KEY NOT NULL,
    goal_id           TEXT NOT NULL,
    objective         TEXT NOT NULL,
    status            TEXT NOT NULL
        CHECK(status IN ('active','paused','blocked','usage_limited','budget_limited','complete')),
    token_budget      INTEGER,
    tokens_used       INTEGER NOT NULL DEFAULT 0,
    time_used_seconds INTEGER NOT NULL DEFAULT 0,
    created_at_ms     INTEGER NOT NULL,
    updated_at_ms     INTEGER NOT NULL
);
"""

_COLUMNS = (
    "session_id",
    "goal_id",
    "objective",
    "status",
    "token_budget",
    "tokens_used",
    "time_used_seconds",
    "created_at_ms",
    "updated_at_ms",
)


class Goal:
    """Immutable snapshot of a goal row (the Python view of a DB row)."""

    __slots__ = (
        "session_id",
        "goal_id",
        "objective",
        "status",
        "token_budget",
        "tokens_used",
        "time_used_seconds",
        "created_at_ms",
        "updated_at_ms",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def is_active(self):
        return self.status == "active"

    def is_terminal(self):
        return self.status in (
            "complete",
            "blocked",
            "usage_limited",
            "budget_limited",
        )

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def validate_objective(text):
    """Return a trimmed objective, or raise ValueError if it is invalid.

    Mirrors Codex's ``validate_thread_goal_objective``: non-empty and at most
    ``MAX_OBJECTIVE_CHARS`` characters.
    """
    if not isinstance(text, str):
        raise ValueError("objective must be a string")
    objective = text.strip()
    if not objective:
        raise ValueError("objective must not be empty")
    if len(objective) > MAX_OBJECTIVE_CHARS:
        raise ValueError(
            f"objective must be at most {MAX_OBJECTIVE_CHARS} characters"
        )
    return objective


def validate_budget(value):
    """Return a positive int budget, or raise ValueError."""
    if value is None:
        return None
    try:
        budget = int(value)
    except (TypeError, ValueError):
        raise ValueError("token budget must be an integer")
    if budget <= 0:
        raise ValueError("token budget must be a positive integer")
    return budget


def _now_ms():
    return int(time.time() * 1000)


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _row_to_goal(row):
    if row is None:
        return None
    return Goal(**{k: row[k] for k in _COLUMNS})


class GoalStore:
    """SQLite-backed goal persistence keyed by ``session_id``."""

    def __init__(self, db_path):
        self.db_path = db_path

    def _connect(self):
        return _connect(self.db_path)

    def get_goal(self, session_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _row_to_goal(row)

    def replace_goal(self, session_id, objective, token_budget=None):
        """Create or overwrite the goal for ``session_id``."""
        objective = validate_objective(objective)
        token_budget = validate_budget(token_budget)
        now = _now_ms()
        goal_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO thread_goals "
                "(session_id, goal_id, objective, status, token_budget, "
                "tokens_used, time_used_seconds, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, 'active', ?, 0, 0, ?, ?)",
                (session_id, goal_id, objective, token_budget, now, now),
            )
            conn.commit()
        return self.get_goal(session_id)

    def update_status(self, session_id, status):
        if status not in GOAL_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE thread_goals SET status = ?, updated_at_ms = ? "
                "WHERE session_id = ?",
                (status, _now_ms(), session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_goal(session_id)

    def update_objective(self, session_id, objective):
        objective = validate_objective(objective)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE thread_goals SET objective = ?, updated_at_ms = ? "
                "WHERE session_id = ?",
                (objective, _now_ms(), session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_goal(session_id)

    def update_budget(self, session_id, token_budget):
        token_budget = validate_budget(token_budget)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE thread_goals SET token_budget = ?, updated_at_ms = ? "
                "WHERE session_id = ?",
                (token_budget, _now_ms(), session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_goal(session_id)

    def account_usage(self, session_id, tokens_delta, seconds_delta):
        """Add usage deltas to an existing goal. Returns the updated goal."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE thread_goals "
                "SET tokens_used = tokens_used + ?, "
                "    time_used_seconds = time_used_seconds + ?, "
                "    updated_at_ms = ? "
                "WHERE session_id = ?",
                (int(tokens_delta), int(seconds_delta), _now_ms(), session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_goal(session_id)

    def delete_goal(self, session_id):
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM thread_goals WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            return cur.rowcount > 0
