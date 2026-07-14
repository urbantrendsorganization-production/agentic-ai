"""The agent loop: wait → act → verify → respond & log (proposal §4).

`handle_message` is the whole P1 gate. Given a session and a user message it:

  1. (wait)   — the caller already received the message; we record it.
  2. act      — the planner picks a whitelisted tool (or a plain reply).
  3. verify   — run the tool, check the result against intent; retry once,
                then escalate on failure. This is what makes it *agentic*.
  4. respond  — compose the reply.
  & log       — every step appends an AgentEvent so the session is fully
                reconstructable from the log alone (success metric §10).

Everything runs in one DB transaction per message so a crash never leaves a
half-written turn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from .models import AgentEvent, Message, Session
from .planner import get_planner
from .tools import registry

log = logging.getLogger(__name__)


@dataclass
class TurnResult:
    reply: str
    escalated: bool
    events: int


class _EventWriter:
    """Assigns monotonic seq numbers and appends AgentEvents for a session."""

    def __init__(self, session: Session) -> None:
        self.session = session
        current = session.events.aggregate(m=Max("seq"))["m"]
        self._seq = (current or 0)
        self.count = 0

    def log(self, step: str, **payload) -> AgentEvent:
        self._seq += 1
        self.count += 1
        return AgentEvent.objects.create(
            session=self.session, seq=self._seq, step=step, payload=payload
        )


def _build_history(session: Session) -> list[dict]:
    """Prior transcript as Anthropic-style messages (kept small for P1)."""
    turns = session.messages.order_by("created_at")[:20]
    role_map = {Message.ROLE_USER: "user", Message.ROLE_AGENT: "assistant"}
    return [{"role": role_map[m.role], "content": m.text} for m in turns]


@transaction.atomic
def handle_message(session: Session, user_text: str) -> TurnResult:
    planner = get_planner()
    events = _EventWriter(session)

    # 1. wait → the message arrived; persist it and log receipt.
    Message.objects.create(session=session, role=Message.ROLE_USER, text=user_text)
    events.log(AgentEvent.STEP_RECEIVE, text=user_text)

    history = _build_history(session)
    tool_specs = registry.specs()

    reply = ""
    escalated = False

    # act + verify, with one retry before escalation (proposal §4/§8).
    for attempt in range(1, settings.AGENT_MAX_STEPS + 1):
        decision = planner.decide(user_text=user_text, tool_specs=tool_specs, history=history)

        if decision.kind == "reply":
            events.log(AgentEvent.STEP_ACT, decision="reply")
            reply = decision.text
            break

        tool = registry.get(decision.tool_name)
        events.log(
            AgentEvent.STEP_ACT,
            decision="tool",
            tool=decision.tool_name,
            args=decision.tool_args,
            attempt=attempt,
        )

        # Guardrail: only whitelisted tools, and re-validate their input.
        if tool is None:
            events.log(AgentEvent.STEP_VERIFY, ok=False, error="unknown_tool",
                       tool=decision.tool_name)
            continue
        try:
            clean_args = tool.validate(decision.tool_args or {})
        except ValueError as exc:
            events.log(AgentEvent.STEP_VERIFY, ok=False, error="invalid_args", detail=str(exc))
            continue

        try:
            result = tool.run(clean_args, session=session)
        except Exception as exc:  # a tool blowing up is a verify failure, not a 500
            log.exception("Tool %s raised", decision.tool_name)
            events.log(AgentEvent.STEP_VERIFY, ok=False, error="tool_exception", detail=str(exc))
            continue

        # verify: did the tool achieve the intent? (each Tool owns its check)
        verified = tool.verify(clean_args, result)
        events.log(
            AgentEvent.STEP_VERIFY,
            ok=verified,
            tool=decision.tool_name,
            result=result.data,
            error="" if verified else (result.error or "verify_failed"),
        )
        if verified:
            reply = planner.compose_reply(tool_summary=result.summary, history=history)
            break
        # else: loop and retry / try again until AGENT_MAX_STEPS
    else:
        # Exhausted attempts without a verified outcome → escalate.
        escalated = True
        reply = (
            "I couldn't complete that just now, so I've flagged it for a human on "
            "the UrbanTrends team. They'll follow up shortly."
        )

    # 4. respond & log.
    Message.objects.create(session=session, role=Message.ROLE_AGENT, text=reply)
    events.log(AgentEvent.STEP_RESPOND, text=reply, escalated=escalated)

    return TurnResult(reply=reply, escalated=escalated, events=events.count)
