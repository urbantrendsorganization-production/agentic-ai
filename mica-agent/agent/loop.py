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

from . import pricing
from .forms import FormError, validate_submission
from .models import AgentEvent, Message, OrderDraft, Session, Ticket
from .planner import get_planner
from .tickets import open_ticket
from .tools import registry

log = logging.getLogger(__name__)


@dataclass
class TurnResult:
    reply: str
    escalated: bool
    events: int
    # A client-side action the widget must execute (e.g. show a form, navigate),
    # lifted from the verified tool's result. None for plain replies.
    action: dict | None = None
    # Aggregate Claude token usage for the turn (sum over every planner call this
    # turn, incl. retries). None when no model ran — i.e. the keyless stub (P6).
    usage: dict | None = None


def _add_usage(total: dict, usage: dict | None) -> None:
    """Fold one planner call's usage into the running per-turn total."""
    if not usage:
        return
    total["input_tokens"] += usage.get("input_tokens", 0)
    total["output_tokens"] += usage.get("output_tokens", 0)
    total["calls"] += 1
    if usage.get("model") and "model" not in total:
        total["model"] = usage["model"]


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
    action: dict | None = None
    # Per-turn token spend, accumulated across every planner call incl. retries.
    usage_total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    # act + verify, with one retry before escalation (proposal §4/§8).
    for attempt in range(1, settings.AGENT_MAX_STEPS + 1):
        decision = planner.decide(user_text=user_text, tool_specs=tool_specs, history=history)
        _add_usage(usage_total, decision.usage)

        if decision.kind == "reply":
            events.log(AgentEvent.STEP_ACT, decision="reply", usage=decision.usage)
            reply = decision.text
            break

        tool = registry.get(decision.tool_name)
        events.log(
            AgentEvent.STEP_ACT,
            decision="tool",
            tool=decision.tool_name,
            args=decision.tool_args,
            attempt=attempt,
            usage=decision.usage,
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
            # Surface the verified tool's structured result to the widget. Turns
            # that carry a client-side step set data["action"] (show_form,
            # navigate); others (e.g. order created) carry their outcome.
            if isinstance(result.data, dict) and result.data:
                action = result.data
                # A tool can hand off to a human (e.g. create_ticket); it signals
                # that in its result and the turn is marked escalated.
                escalated = bool(result.data.get("escalated"))
            break
        # else: loop and retry / try again until AGENT_MAX_STEPS
    else:
        # Exhausted attempts without a verified outcome → escalate to a human by
        # opening a ticket with the transcript attached (proposal §8).
        escalated = True
        ticket = open_ticket(
            session,
            subject=f"Unresolved request: {user_text[:120]}",
            category="other",
            reason=Ticket.REASON_VERIFY_EXHAUSTED,
        )
        events.log(AgentEvent.STEP_ERROR, reason="verify_exhausted", ticket_ref=ticket.ref)
        action = {"action": "ticket_created", "ticket_ref": ticket.ref, "escalated": True}
        reply = (
            f"I couldn't complete that just now, so I've opened ticket {ticket.ref} for "
            "a human on the UrbanTrends team — they'll follow up shortly."
        )

    # 4. respond & log. The turn's total token spend rides on the respond event
    # so an auditor sees per-turn cost inline in the timeline (None for the stub).
    turn_usage = usage_total if usage_total["calls"] else None
    Message.objects.create(session=session, role=Message.ROLE_AGENT, text=reply)
    events.log(AgentEvent.STEP_RESPOND, text=reply, escalated=escalated, usage=turn_usage)

    return TurnResult(
        reply=reply, escalated=escalated, events=events.count, action=action, usage=turn_usage
    )


@transaction.atomic
def submit_order_form(session: Session, raw_form: dict) -> TurnResult:
    """Deterministic form-submission turn (proposal §5 dynamic forms, §8 money).

    Not routed through the planner: a structured submission needs validation and
    a rules-engine quote, not an LLM. Still fully logged as a turn so the audit
    trail is unbroken. Raises FormError (→ 400) on invalid input.
    """
    draft = (
        session.order_drafts.filter(status=OrderDraft.STATUS_GATHERING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        raise FormError({"form": "no order in progress — start an order first"})

    # Validate before writing anything; invalid submissions never touch the log.
    params = validate_submission(draft.service, raw_form)
    quote = pricing.quote(draft.service, params)

    events = _EventWriter(session)
    events.log(AgentEvent.STEP_RECEIVE, kind="form_submission", service=draft.service, raw=raw_form)
    events.log(AgentEvent.STEP_ACT, decision="quote", service=draft.service, params=params)

    draft.params = params
    draft.quote = quote.as_dict()
    draft.status = OrderDraft.STATUS_QUOTED
    draft.save(update_fields=["params", "quote", "status", "updated_at"])
    events.log(AgentEvent.STEP_VERIFY, ok=True, quote=quote.as_dict())

    reply = (
        "Here's your quote:\n"
        f"{quote.summary()}\n\n"
        "Reply 'confirm' to place the order (it'll be pending with the team), "
        "or tell me what to adjust."
    )
    Message.objects.create(session=session, role=Message.ROLE_AGENT, text=reply)
    events.log(AgentEvent.STEP_RESPOND, text=reply)

    return TurnResult(
        reply=reply,
        escalated=False,
        events=events.count,
        action={"action": "quote", "quote": quote.as_dict(), "draft_status": draft.status},
    )
