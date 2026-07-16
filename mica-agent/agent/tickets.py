"""Support-ticket creation with the transcript attached (proposal §5, §8).

A ticket is the agent's escalation artifact: whenever it can't resolve a request
— either the model deliberately hands off, or the loop exhausts its retries — it
opens a Ticket with a *server-assembled* snapshot of the conversation. The model
never supplies the transcript; it only proposes a subject/category, which we
re-validate. The transcript is authoritative data lifted straight from the
Message log, so the human who picks up the ticket sees exactly what happened.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from django.conf import settings

from .models import Session, Ticket

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenedTicket:
    """The durable escalation artifact, whichever backend created it.

    Callers only need `ref` (read back to the customer) and `category`.
    """

    ref: str
    category: str = "other"
    id: str = ""
    status: str = "open"


def snapshot_transcript(session: Session) -> list[dict]:
    """Server-authored conversation snapshot for a ticket (never model-supplied)."""
    return [
        {"role": m.role, "text": m.text, "at": m.created_at.isoformat()}
        for m in session.messages.order_by("created_at")
    ]


def open_ticket(session: Session, *, subject: str, category: str, reason: str) -> OpenedTicket:
    """Open an escalation ticket with the transcript attached.

    Backend (system of record) when URBANTRENDS_API_BASE is set, else a local
    Ticket row. If the backend call fails, fall back to a local ticket so an
    escalation is never silently lost — the ticket is the safety net itself.
    """
    if getattr(settings, "URBANTRENDS_API_BASE", ""):
        try:
            return _open_backend(session, subject=subject, category=category, reason=reason)
        except Exception:  # backend down → don't drop the escalation, keep it locally
            log.exception("backend ticket create failed; falling back to a local ticket")
    return _open_local(session, subject=subject, category=category, reason=reason)


def _open_local(session: Session, *, subject: str, category: str, reason: str) -> OpenedTicket:
    ticket = Ticket.objects.create(
        session=session,
        customer_ref=session.customer_ref,
        subject=subject,
        category=category,
        reason=reason,
        transcript=snapshot_transcript(session),
    )
    return OpenedTicket(ref=ticket.ref, category=ticket.category, id=str(ticket.id),
                        status=ticket.status)


def _open_backend(session: Session, *, subject: str, category: str, reason: str) -> OpenedTicket:
    from .backend import get_client

    body = {
        "subject": subject,
        "category": category,
        "reason": reason,
        "customer_ref": session.customer_ref,
        "session_ref": str(session.id),
        "transcript": snapshot_transcript(session),
    }
    data = get_client().post_json(
        "/tickets",
        body,
        session_cookie=getattr(session, "_ut_session_cookie", None),
        idempotency_key=str(uuid.uuid4()),
    )
    return OpenedTicket(
        ref=data["ref"],
        category=category,
        id=data.get("ticket_id", ""),
        status=data.get("status", "open"),
    )
