"""SQLite-backed task store, shared by the web UI (`webapp.py`) and the
planner's tasks source (`sources/tasks_source.py`).

Kept deliberately small: a single `tasks` table plus a handful of functions.
Every call takes the db path explicitly so there's no hidden global state.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

PRIORITIES = ("high", "normal", "low")
STATUSES = ("open", "waiting", "done")
_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


@dataclass
class Task:
    id: int
    title: str
    priority: str
    due: str
    status: str
    created_at: str


@contextmanager
def _conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _conn(db_path) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                priority   TEXT NOT NULL DEFAULT 'normal',
                due        TEXT NOT NULL DEFAULT '',
                status     TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            )
            """
        )


def add_task(db_path: str, title: str, priority: str = "normal",
             due: str = "", status: str = "open") -> None:
    if priority not in PRIORITIES:
        priority = "normal"
    if status not in STATUSES:
        status = "open"
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO tasks (title, priority, due, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (title.strip(), priority, due.strip(), status,
             dt.datetime.now().isoformat(timespec="seconds")),
        )


def list_tasks(db_path: str, status: str | None = None) -> list[Task]:
    query = "SELECT * FROM tasks"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    with _conn(db_path) as c:
        rows = c.execute(query, params).fetchall()
    tasks = [Task(**dict(r)) for r in rows]
    # Highest priority first, then oldest first.
    tasks.sort(key=lambda t: (_PRIORITY_RANK.get(t.priority, 1), t.created_at))
    return tasks


def set_status(db_path: str, task_id: int, status: str) -> None:
    if status not in STATUSES:
        return
    with _conn(db_path) as c:
        c.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))


def delete_task(db_path: str, task_id: int) -> None:
    with _conn(db_path) as c:
        c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def render_for_planner(db_path: str) -> str:
    """Render open + waiting tasks as a compact markdown block for Claude.

    Returns "" when there's nothing actionable, so the caller can fall back to
    a legacy markdown file.
    """
    open_tasks = list_tasks(db_path, status="open")
    waiting = list_tasks(db_path, status="waiting")
    if not open_tasks and not waiting:
        return ""

    lines = ["Today's open tasks (managed via the task UI):"]
    for t in open_tasks:
        bits = []
        if t.priority != "normal":
            bits.append(f"{t.priority} priority")
        if t.due:
            bits.append(f"due {t.due}")
        suffix = f" ({', '.join(bits)})" if bits else ""
        lines.append(f"- {t.title}{suffix}")

    if waiting:
        lines.append("")
        lines.append("Waiting on / blocked:")
        for t in waiting:
            suffix = f" (due {t.due})" if t.due else ""
            lines.append(f"- {t.title}{suffix}")

    return "\n".join(lines)
