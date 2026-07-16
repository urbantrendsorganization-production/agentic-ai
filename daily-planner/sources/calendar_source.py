"""Google Calendar: read today's events, and write time-blocked events.

First run opens a browser to authorise and writes a reusable token to
`google_token.json`. Requires `google_credentials.json` (an OAuth *Desktop app*
client downloaded from the Google Cloud console). If neither is present the
read source is silently skipped.

The scope is `calendar.events` (read + write of events) so the planner can push
its time-blocked schedule onto your calendar. If you previously authorised with
the old read-only scope, delete `google_token.json` and re-run once to re-consent.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

log = logging.getLogger(__name__)

# calendar.events grants both reading and creating events on the user's calendars.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CREDENTIALS_FILE = "google_credentials.json"
TOKEN_FILE = "google_token.json"


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif os.path.exists(CREDENTIALS_FILE):
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
    else:
        return None
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def _service():
    """Authorised Calendar API client, or None if not configured/authorised."""
    if not os.path.exists(TOKEN_FILE) and not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        from googleapiclient.discovery import build

        creds = _load_credentials()
        if not creds:
            return None
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar service unavailable: %s", exc)
        return None


def _fmt_event(event: dict) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    summary = event.get("summary", "(no title)")
    # Show just HH:MM for timed events; leave all-day events as-is.
    if "T" in start:
        try:
            start = dt.datetime.fromisoformat(start).strftime("%H:%M")
        except ValueError:
            pass
    location = event.get("location")
    suffix = f" @ {location}" if location else ""
    return f"- {start}  {summary}{suffix}"


def gather_calendar(timezone: str = "UTC") -> str:
    if not os.path.exists(TOKEN_FILE) and not os.path.exists(CREDENTIALS_FILE):
        return ""
    try:
        service = _service()
        if not service:
            return ""

        now = dt.datetime.now(dt.timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59)
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        if not events:
            return "Calendar: nothing scheduled for the rest of today."
        return "Today's calendar:\n" + "\n".join(_fmt_event(e) for e in events)
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar source failed: %s", exc)
        return f"Calendar: unavailable ({exc})."


def _local_to_rfc3339(local_iso: str, timezone: str) -> str:
    """'YYYY-MM-DDTHH:MM:SS' (naive, local) → RFC3339 with the zone's offset."""
    try:
        from zoneinfo import ZoneInfo

        naive = dt.datetime.fromisoformat(local_iso)
        return naive.replace(tzinfo=ZoneInfo(timezone)).isoformat()
    except Exception:  # noqa: BLE001 — fall back to UTC 'Z'
        return local_iso.rstrip("Z") + "Z"


def _existing_keys(service, events, timezone: str) -> set[tuple[str, str]]:
    """(title, start-to-the-minute) for events already on the calendar on the
    plan's day(s) — used to skip duplicates when the planner re-runs."""
    keys: set[tuple[str, str]] = set()
    for day in {e.start[:10] for e in events if len(e.start) >= 10}:
        try:
            res = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=_local_to_rfc3339(f"{day}T00:00:00", timezone),
                    timeMax=_local_to_rfc3339(f"{day}T23:59:59", timezone),
                    singleEvents=True,
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("dedup lookup failed for %s: %s", day, exc)
            continue
        for ev in res.get("items", []):
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            keys.add((ev.get("summary", "").strip().lower(), start[:16]))
    return keys


def create_events(events, timezone: str = "UTC"):
    """Create calendar events from the planner's schedule.

    `events` is an iterable of objects with `.title`, `.start`, `.end` (local ISO
    'YYYY-MM-DDTHH:MM:SS') and optional `.location` / `.description`. Events that
    already exist (same title + start minute) are skipped, so daily re-runs don't
    double-book. Never raises. Returns (created, skipped, failed) title lists.
    """
    created: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    events = list(events)
    if not events:
        return created, skipped, failed

    service = _service()
    if not service:
        log.warning("cannot create events — calendar not authorised.")
        return created, skipped, [getattr(e, "title", "?") for e in events]

    existing = _existing_keys(service, events, timezone)
    for e in events:
        key = (e.title.strip().lower(), e.start[:16])
        if key in existing:
            skipped.append(e.title)
            continue
        body = {
            "summary": e.title,
            "start": {"dateTime": e.start, "timeZone": timezone},
            "end": {"dateTime": e.end, "timeZone": timezone},
            # Tag ours so they're findable later (e.g. for cleanup).
            "extendedProperties": {"private": {"source": "daily-planner"}},
        }
        if getattr(e, "location", None):
            body["location"] = e.location
        if getattr(e, "description", None):
            body["description"] = e.description
        try:
            service.events().insert(calendarId="primary", body=body).execute()
            created.append(e.title)
            existing.add(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to create event %r: %s", e.title, exc)
            failed.append(e.title)

    return created, skipped, failed
