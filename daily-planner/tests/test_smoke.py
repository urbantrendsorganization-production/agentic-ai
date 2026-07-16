"""Fast, network-free smoke tests — the safety net the CI pipeline runs.

These import the app, exercise the graceful-degradation contract every source
promises (never raise; return "" when unconfigured), and check the calendar
event helpers without ever touching Google.
"""
from __future__ import annotations

import importlib


def test_app_modules_import():
    for mod in ("config", "planner", "main", "webapp", "sources"):
        importlib.import_module(mod)


def test_sources_degrade_when_unconfigured():
    from sources import gather_local, gather_news, gather_weather

    # Nothing configured → empty string, never an exception.
    assert gather_local([], []) == ""
    assert gather_local(["/no/such/path"], ["/no/such/repo"]) == ""
    assert gather_weather("") == ""
    assert gather_news([]) == ""


def test_local_source_reads_a_file(tmp_path):
    from sources import gather_local

    note = tmp_path / "today.md"
    note.write_text("ship the calendar feature")
    out = gather_local([str(note)], [])
    assert "today.md" in out
    assert "ship the calendar feature" in out


def test_planned_event_and_plan_shape():
    from planner import DailyPlan, PlannedEvent

    plan = DailyPlan(subject="s", whatsapp_message="w", email_body="e")
    assert plan.events == []  # defaults to empty, not None

    ev = PlannedEvent(
        title="Client call — Acme API",
        start="2026-07-03T11:00:00",
        end="2026-07-03T11:30:00",
    )
    assert ev.location is None


def test_rfc3339_conversion_applies_offset():
    from sources.calendar_source import _local_to_rfc3339

    assert _local_to_rfc3339("2026-07-03T11:00:00", "Africa/Nairobi") == "2026-07-03T11:00:00+03:00"


def test_create_events_without_auth_does_not_raise(tmp_path, monkeypatch):
    from planner import PlannedEvent
    from sources import create_events

    # Run from a dir with no google_credentials.json/token so the OAuth flow is
    # never triggered (mirrors CI, and avoids opening a browser locally).
    monkeypatch.chdir(tmp_path)
    ev = PlannedEvent(title="x", start="2026-07-03T09:00:00", end="2026-07-03T09:30:00")
    created, skipped, failed = create_events([ev], "Africa/Nairobi")
    assert created == [] and skipped == [] and failed == ["x"]
