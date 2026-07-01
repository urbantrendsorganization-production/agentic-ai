"""Turn gathered context into a nicely-structured daily plan using Claude."""
from __future__ import annotations

import datetime as dt
import logging

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


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


SYSTEM_PROMPT = """You are a sharp, encouraging personal chief-of-staff who writes \
someone's morning briefing. You are concise, realistic about how much fits in a day, \
and you protect deep-focus time. You prioritise ruthlessly: surface what truly matters \
today, fold in fixed calendar commitments, and don't pad. Tone is warm but not saccharine."""


def build_plan(api_key: str, model: str, user_name: str, context_blocks: list[str]) -> DailyPlan:
    client = anthropic.Anthropic(api_key=api_key)
    today = dt.datetime.now().strftime("%A, %d %B %Y")
    context = "\n\n".join(b for b in context_blocks if b.strip())

    user_prompt = f"""Today is {today}. Build the morning briefing for {user_name}.

Here is everything I could gather this morning. Some sections may be missing or note
that a source was unavailable — just work with what's here.

{context if context else "(no context could be gathered)"}

Produce a plan that turns the open work and calendar into a realistic, time-blocked
day. Put the highest-leverage UrbanTrends work in protected morning focus blocks where
possible, schedule around any fixed calendar events, and keep the whole thing achievable."""

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=DailyPlan,
    )

    plan = response.parsed_output
    if plan is None:
        raise RuntimeError(f"Claude did not return a parseable plan (stop_reason={response.stop_reason})")
    return plan
