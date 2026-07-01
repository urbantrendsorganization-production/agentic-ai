"""Open tasks for the planner.

Primary source is the SQLite store managed via the web UI (`webapp.py`); if
that has nothing actionable we fall back to a legacy markdown/plain-text file.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def gather_tasks(path: str = "", db_path: str = "") -> str:
    # Prefer the task-UI database.
    if db_path and os.path.exists(db_path):
        try:
            import task_store

            block = task_store.render_for_planner(db_path)
            if block:
                return block
        except Exception as exc:  # noqa: BLE001
            log.warning("task store unavailable, falling back to file: %s", exc)

    # Legacy markdown file fallback.
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return ""
        return f"Personal todo list ({os.path.basename(path)}):\n{content}"
    except Exception as exc:  # noqa: BLE001
        log.warning("tasks source failed: %s", exc)
        return f"Tasks file: unavailable ({exc})."
