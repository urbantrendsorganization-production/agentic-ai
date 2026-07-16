"""Order placement — deterministic money, backend as system of record (§8).

`place_order` turns a *quoted* OrderDraft into a placed order. Two backends
behind one call, selected by URBANTRENDS_API_BASE:

* **backend** (live): POST /orders referencing the draft's server-issued
  `quote_id`; the amount is looked up server-side from the quote, never sent.
  The urbantrends.dev backend is the system of record — Mica keeps only the
  returned ref (in the draft + the audit log), no local Order row.
* **local** (keyless dev/tests): create a pending Order from the draft's quote,
  exactly as before.

Either way the request carries no model-chosen price. A returned
`{"created": False, "reason": ...}` is a *business* outcome (e.g. the quote
expired → re-quote), not a failure; a provider error raises so the loop retries
then escalates.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from . import catalog
from .models import Order

# Backend error codes that are business outcomes, not provider faults. Each maps
# to a graceful reply (re-quote, or sign-in) rather than a retry/escalation.
_BUSINESS_CODES = {
    "quote_expired", "quote_unavailable", "quote_not_found", "no_quote",
    "not_authenticated",  # 401 → the loop asks the visitor to sign in first
}


def place_order(session, draft) -> dict:
    """Place a quoted draft. Returns {created, ref, status, currency, amount, label}
    or {created: False, reason}. Does not change the draft status (the caller does).
    """
    if getattr(settings, "URBANTRENDS_API_BASE", ""):
        return _place_backend(session, draft)
    return _place_local(session, draft)


def _place_local(session, draft) -> dict:
    quote = draft.quote
    order = Order.objects.create(
        session=session,
        customer_ref=session.customer_ref,
        service=draft.service,
        params=draft.params,
        currency=quote["currency"],
        amount=Decimal(quote["amount"]),
        breakdown=quote["breakdown"],
    )
    return {
        "created": True,
        "order_id": str(order.id),
        "ref": str(order.id)[:8],
        "status": order.status,
        "currency": order.currency,
        "amount": str(order.amount),
        "label": catalog.get(draft.service).label,
    }


def _place_backend(session, draft) -> dict:
    from .backend import BackendError, get_client

    quote = draft.quote or {}
    cookie = getattr(session, "_ut_session_cookie", None)
    # Prefer the server-issued quote_id (amount looked up server-side); fall back
    # to service + params for the backend to recompute. Never send an amount.
    quote_id = quote.get("quote_id")
    body = {"quote_id": quote_id} if quote_id else {"service": draft.service, "params": draft.params}
    try:
        data = get_client().post_json(
            "/orders", body, session_cookie=cookie, idempotency_key=str(draft.id)
        )
    except BackendError as exc:
        if exc.code in _BUSINESS_CODES:
            return {"created": False, "reason": exc.code}
        raise  # provider down / unexpected → loop treats as failure (retry/escalate)
    return {
        "created": True,
        "order_id": data.get("order_id", ""),
        "ref": data.get("ref", ""),
        "status": data.get("status", "pending"),
        "currency": data.get("currency", quote.get("currency", "KES")),
        "amount": str(data.get("amount", quote.get("amount", ""))),
        "label": catalog.get(draft.service).label,
    }
