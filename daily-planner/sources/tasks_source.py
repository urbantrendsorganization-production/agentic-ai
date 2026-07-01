"""A local markdown / plain-text todo list."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def gather_tasks(path: str) -> str:
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
