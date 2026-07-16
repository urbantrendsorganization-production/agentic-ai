"""Support tools (proposal §5 — issue resolution, §8 — escalation).

Two tools:

* `answer_question` — answer a common question from the knowledge base. The model
  only ever *selects* a whitelisted topic key; the answer text is served from
  agent/kb.py, never composed by the model. So support answers are reviewed,
  canned content — the model can't hallucinate policy or prices.
* `create_ticket` — hand off to a human. The model proposes a subject and
  category only; the loop attaches a server-authored transcript snapshot
  (agent/tickets.py). This is the escalation path: anything the agent can't
  resolve becomes a durable ticket carrying the full conversation for a human.
"""
from __future__ import annotations

from typing import Any

from .. import kb
from ..models import Ticket
from ..tickets import open_ticket
from .base import Tool, ToolResult, register


@register
class AnswerQuestionTool(Tool):
    name = "answer_question"
    description = (
        "Answer a common customer question (ordering, payment, timelines, revisions, "
        "services, order status) from the UrbanTrends knowledge base. Pick the "
        "closest topic. Only answer from the knowledge base — never invent an answer."
    )
    # Enum filled per turn from the active KB (may be backend-sourced), so no
    # network call at import time. spec() is the contract sent to the model.
    input_schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Which knowledge-base topic best answers the question.",
            }
        },
        "required": ["topic"],
    }

    def spec(self) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "topic": dict(self.input_schema["properties"]["topic"], enum=kb.keys()),
            },
            "required": ["topic"],
        }
        return {"name": self.name, "description": self.description, "input_schema": schema}

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = (args.get("topic") or "").strip()
        try:
            kb.get(topic)
        except KeyError:
            raise ValueError(f"unknown topic: {topic!r}")
        return {"topic": topic}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        article = kb.get(args["topic"])
        return ToolResult(
            ok=True,
            data={"action": "kb_answer", "topic": article.key},
            summary=article.answer,
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        # Intent check: we served a real, whitelisted article.
        return result.ok and result.data.get("topic") in set(kb.keys())


@register
class CreateTicketTool(Tool):
    name = "create_ticket"
    description = (
        "Open a support ticket for a human on the UrbanTrends team when you can't "
        "resolve the customer's issue from the knowledge base, or when they ask to "
        "speak to a person. The full conversation is attached automatically. Give a "
        "short subject summarising the issue."
    )
    _CATEGORIES = {c for c, _ in Ticket.CATEGORY_CHOICES}
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "A short summary of what the customer needs help with.",
            },
            "category": {
                "type": "string",
                "enum": sorted(_CATEGORIES),
                "description": "The kind of issue. Use 'other' if unsure.",
            },
        },
        "required": ["subject"],
    }

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        subject = (args.get("subject") or "").strip()
        if not subject:
            raise ValueError("subject is required")
        category = (args.get("category") or "other").strip().lower()
        if category not in self._CATEGORIES:
            category = "other"
        return {"subject": subject[:200], "category": category}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        ticket = open_ticket(
            session,
            subject=args["subject"],
            category=args["category"],
            reason=Ticket.REASON_AGENT_HANDOFF,
        )
        return ToolResult(
            ok=True,
            data={
                "action": "ticket_created",
                "ticket_ref": ticket.ref,
                "category": ticket.category,
                # Signals a human handoff so the loop marks the turn escalated.
                "escalated": True,
            },
            summary=(
                f"I've opened ticket {ticket.ref} for our team with this conversation "
                "attached. Someone will follow up with you shortly."
            ),
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        return result.ok and bool(result.data.get("ticket_ref"))
