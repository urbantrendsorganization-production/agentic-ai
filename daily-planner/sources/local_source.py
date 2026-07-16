"""Local machine context for the planner.

Pulls context off *this* computer so the morning briefing knows what's on disk
and what you were working on. Two kinds of input, both optional:

  * paths  — files and folders you point it at. Files are read (size-capped);
             folders contribute a list of their recently-changed files.
  * repos  — git repositories; each contributes yesterday's commit subjects,
             so "what did I do yesterday" lands in the plan automatically.

Like every source here it never raises: anything missing or unreadable is
skipped or reported inline, so a bad path never blocks your morning plan.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

log = logging.getLogger(__name__)


def _read_file(path: str, max_bytes: int) -> str:
    """First `max_bytes` of a text file, with a truncation note if clipped."""
    try:
        size = os.path.getsize(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes).strip()
        if not content:
            return ""
        clipped = "\n… (truncated)" if size > max_bytes else ""
        return f"• {os.path.basename(path)}:\n{content}{clipped}"
    except Exception as exc:  # noqa: BLE001
        log.warning("local file %s unreadable: %s", path, exc)
        return f"• {os.path.basename(path)}: unavailable ({exc})."


def _recent_in_dir(path: str, days: int, limit: int = 15) -> str:
    """Files under `path` modified within `days`, newest first."""
    cutoff = time.time() - days * 86400
    hits: list[tuple[float, str]] = []
    try:
        for root, dirs, files in os.walk(path):
            # Skip noise that would never be useful morning context.
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d not in {"node_modules", "__pycache__", ".venv", "venv"}]
            for name in files:
                if name.startswith("."):
                    continue
                fp = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(fp)
                except OSError:
                    continue
                if mtime >= cutoff:
                    hits.append((mtime, os.path.relpath(fp, path)))
    except Exception as exc:  # noqa: BLE001
        log.warning("local dir %s unreadable: %s", path, exc)
        return f"• {os.path.basename(path.rstrip('/'))}/: unavailable ({exc})."

    if not hits:
        return ""
    hits.sort(reverse=True)
    lines = "\n".join(f"    - {rel}" for _, rel in hits[:limit])
    more = f"\n    … +{len(hits) - limit} more" if len(hits) > limit else ""
    label = os.path.basename(path.rstrip("/")) or path
    return f"• {label}/ — changed in last {days}d:\n{lines}{more}"


def _git_recent(repo: str, days: int) -> str:
    """Commit subjects from `repo` within `days` (any author)."""
    if not os.path.isdir(os.path.join(repo, ".git")):
        log.warning("local repo %s is not a git checkout", repo)
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", f"--since={days}.days.ago",
             "--pretty=format:%h %s"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("git log failed for %s: %s", repo, exc)
        return ""
    commits = out.stdout.strip()
    if not commits:
        return ""
    name = os.path.basename(repo.rstrip("/")) or repo
    lines = "\n".join(f"    - {c}" for c in commits.splitlines())
    return f"• {name} — commits in last {days}d:\n{lines}"


def gather_local(paths: list[str], repos: list[str],
                 max_file_bytes: int = 4000, recent_days: int = 2) -> str:
    """Assemble a local-machine context block. Returns '' if nothing configured."""
    if not paths and not repos:
        return ""

    log.info("gathering local context…")
    parts: list[str] = []

    for raw in paths:
        p = os.path.expanduser(raw)
        if not os.path.exists(p):
            log.warning("local path does not exist: %s", p)
            continue
        block = _recent_in_dir(p, recent_days) if os.path.isdir(p) \
            else _read_file(p, max_file_bytes)
        if block:
            parts.append(block)

    for raw in repos:
        block = _git_recent(os.path.expanduser(raw), recent_days)
        if block:
            parts.append(block)

    if not parts:
        return ""
    return "On this computer:\n" + "\n".join(parts)
