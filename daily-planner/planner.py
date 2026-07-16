"""Turn gathered context into a nicely-structured daily plan using Claude."""
from __future__ import annotations

import datetime as dt
import logging

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class PlannedEvent(BaseModel):
    """A single time-block Claude wants on the calendar for the plan's day."""

    title: str = Field(description="Short event title, e.g. 'Client call — Acme API' or 'Deep work: auth refactor'")
    start: str = Field(description="Local start time as ISO 'YYYY-MM-DDTHH:MM:SS' on the plan's date")
    end: str = Field(description="Local end time as ISO 'YYYY-MM-DDTHH:MM:SS' on the plan's date, after start")
    location: str | None = Field(default=None, description="Optional: place or link, e.g. 'Google Meet', 'Zoom'")
    description: str | None = Field(default=None, description="Optional: one or two lines of agenda/context")


class DailyPlan(BaseModel):
    """Structured plan returned by Claude."""

    subject: str = Field(description="Email subject line, e.g. 'Your plan for Mon 30 Jun'")
    whatsapp_message: str = Field(
        description=(
            "A warm, motivating wake-up message under 600 characters for WhatsApp. "
            "Plain text only (no markdown). Lead with a one-line greeting, the "
            "weather, then the 3 most important things to focus on today."
        )
    )
    email_body: str = Field(
        description=(
            "A fuller daily plan in clean markdown for email: greeting, weather, "
            "a prioritised & time-blocked schedule for the day, the UrbanTrends "
            "items that matter most, and a short news brief at the end."
        )
    )
    events: list[PlannedEvent] = Field(
        default_factory=list,
        description=(
            "The time-blocked schedule expressed as concrete calendar events for the "
            "plan's date: deep-work focus blocks, meetings, and especially any "
            "software-engineering CLIENT CALLS implied by the tasks/context. Do NOT "
            "invent events with no basis in the context. Never overlap events, keep "
            "times realistic, and leave breathing room. Empty list if there is "
            "genuinely nothing worth putting on the calendar."
        ),
    )


SYSTEM_PROMPT = """You are a sharp, encouraging personal chief-of-staff who writes \
someone's morning briefing. You are concise, realistic about how much fits in a day, \
and you protect deep-focus time. You prioritise ruthlessly: surface what truly matters \
today, fold in fixed calendar commitments, and don't pad. Tone is warm but not saccharine."""


def build_plan(api_key: str, model: str, user_name: str, context_blocks: list[str],
               profile: str = "", timezone: str = "UTC") -> DailyPlan:
    client = anthropic.Anthropic(api_key=api_key)
    now = dt.datetime.now()
    today = now.strftime("%A, %d %B %Y")
    iso_date = now.strftime("%Y-%m-%d")
    context = "\n\n".join(b for b in context_blocks if b.strip())

    user_prompt = f"""Today is {today}. Build the morning briefing for {user_name}.

Here is everything I could gather this morning. Some sections may be missing or note
that a source was unavailable — just work with what's here.

{context if context else "(no context could be gathered)"}

Produce a plan that turns the open work and calendar into a realistic, time-blocked
day. Put the highest-leverage UrbanTrends work in protected morning focus blocks where
possible, schedule around any fixed calendar events, and keep the whole thing achievable.

Also return the schedule as `events` — concrete calendar entries for {iso_date} in the
{timezone} timezone. Use ISO datetimes like "{iso_date}T09:00:00". These will be written
to the real Google Calendar, so only include blocks worth committing to (focus blocks,
meetings, and any client calls implied by the work) and never overlap them."""

    system = SYSTEM_PROMPT
    if profile.strip():
        system += (
            "\n\nHere is background on the person you're briefing. Use it to tailor "
            "priorities, tone, focus times, and what you surface — but don't recite "
            "it back to them:\n" + profile.strip()
        )

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        # "low" effort keeps thinking/token spend down for this once-a-day
        # briefing. Bump to "medium" if prioritisation feels shallow.
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=DailyPlan,
    )

    plan = response.parsed_output
    if plan is None:
        raise RuntimeError(f"Claude did not return a parseable plan (stop_reason={response.stop_reason})")
    return plan
