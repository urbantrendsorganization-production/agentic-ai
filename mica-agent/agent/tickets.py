"""Support-ticket creation with the transcript attached (proposal §5, §8).

A ticket is the agent's escalation artifact: whenever it can't resolve a request
— either the model deliberately hands off, or the loop exhausts its retries — it
opens a Ticket with a *server-assembled* snapshot of the conversation. The model
never supplies the transcript; it only proposes a subject/category, which we
re-validate. The transcript is authoritative data lifted straight from the
Message log, so the human who picks up the ticket sees exactly what happened.
"""
from __future__ import annotations

from .models import Session, Ticket


def snapshot_transcript(session: Session) -> list[dict]:
    """Server-authored conversation snapshot for a ticket (never model-supplied)."""
    return [
        {"role": m.role, "text": m.text, "at": m.created_at.isoformat()}
        for m in session.messages.order_by("created_at")
    ]


def open_ticket(session: Session, *, subject: str, category: str, reason: str) -> Ticket:
    """Create an open ticket for the session with the transcript attached."""
    return Ticket.objects.create(
        session=session,
        customer_ref=session.customer_ref,
        subject=subject,
        category=category,
        reason=reason,
        transcript=snapshot_transcript(session),
    )
