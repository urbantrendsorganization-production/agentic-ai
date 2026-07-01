"""Open work pulled from the UrbanTrends project API.

Expects an HTTP(S) endpoint returning JSON — either a top-level array, or an
object with a "results"/"tasks" array. Each task is rendered loosely from
common field names so it works against most Django REST shapes without
hard-coding a schema.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

_TITLE_KEYS = ("title", "name", "summary", "subject")
_DUE_KEYS = ("due", "due_date", "deadline", "due_at")
_PRIORITY_KEYS = ("priority", "importance", "severity")
_STATUS_KEYS = ("status", "state")


def _first(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if d.get(k):
            return str(d[k])
    return None


def _render(task: dict) -> str:
    title = _first(task, _TITLE_KEYS) or "(untitled task)"
    bits = []
    if (status := _first(task, _STATUS_KEYS)):
        bits.append(f"status: {status}")
    if (priority := _first(task, _PRIORITY_KEYS)):
        bits.append(f"priority: {priority}")
    if (due := _first(task, _DUE_KEYS)):
        bits.append(f"due: {due}")
    suffix = f" ({', '.join(bits)})" if bits else ""
    return f"- {title}{suffix}"


def gather_urbantrends(api_url: str, token: str = "", limit: int = 25) -> str:
    if not api_url:
        return ""
    try:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            tasks = data.get("results") or data.get("tasks") or data.get("data") or []
        else:
            tasks = data
        if not isinstance(tasks, list) or not tasks:
            return "UrbanTrends: no open items."

        rendered = [_render(t) for t in tasks[:limit] if isinstance(t, dict)]
        return "UrbanTrends open work:\n" + "\n".join(rendered)
    except Exception as exc:  # noqa: BLE001
        log.warning("UrbanTrends source failed: %s", exc)
        return f"UrbanTrends: unavailable ({exc})."
