"""Today's events from Google Calendar.

First run opens a browser to authorise and writes a reusable token to
`google_token.json`. Requires `google_credentials.json` (an OAuth *Desktop app*
client downloaded from the Google Cloud console). If neither is present the
source is silently skipped.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
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
        from googleapiclient.discovery import build

        creds = _load_credentials()
        if not creds:
            return ""
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

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
