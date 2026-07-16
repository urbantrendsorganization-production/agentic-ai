"""Ordering tools (proposal §5 ordering, §8 guardrails).

The order flow is a small state machine over an OrderDraft:

    start_order      → draft(gathering) + pop the dynamic form
    [form submitted] → draft(quoted) with a server-computed quote  (see views)
    create_order     → Order(pending), gated on a quoted draft

Deterministic-money guardrail: neither tool ever accepts or emits a price. The
model only names a service (start_order) and, after the user confirms, asks to
place the order (create_order). The amount is copied from the draft's quote,
which only the pricing engine writes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .. import catalog
from ..models import OrderDraft
from .base import Tool, ToolResult, register


@register
class StartOrderTool(Tool):
    name = "start_order"
    description = (
        "Begin an order once the customer says what they want to buy. Picks the "
        "service and pops a short form to collect the details needed to quote it. "
        "Never quote a price yourself — the form submission produces the quote."
    )
    # No enum baked in at import time — the service list may come from the
    # backend (catalog.keys() can hit the network). spec() fills it per turn.
    input_schema = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Which service the customer wants to order.",
            }
        },
        "required": ["service"],
    }

    def spec(self) -> dict[str, Any]:
        """Inject the current catalog's service keys as the enum (per turn)."""
        schema = {
            "type": "object",
            "properties": {
                "service": dict(self.input_schema["properties"]["service"], enum=catalog.keys()),
            },
            "required": ["service"],
        }
        return {"name": self.name, "description": self.description, "input_schema": schema}

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        service = (args.get("service") or "").strip()
        try:
            catalog.get(service)
        except KeyError:
            raise ValueError(f"unknown service: {service!r}")
        return {"service": service}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        service = catalog.get(args["service"])
        # One active draft per session: retire any earlier unplaced draft.
        session.order_drafts.exclude(status=OrderDraft.STATUS_PLACED).delete()
        draft = OrderDraft.objects.create(
            session=session, service=service.key, status=OrderDraft.STATUS_GATHERING
        )
        return ToolResult(
            ok=True,
            data={
                "action": "show_form",
                "draft_id": str(draft.id),
                "form": service.form_schema(),
            },
            summary=(
                f"Great — a {service.label.lower()}. I've popped a quick form; fill it in "
                "and I'll work out a precise quote."
            ),
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        return result.ok and result.data.get("action") == "show_form"


@register
class CreateOrderTool(Tool):
    name = "create_order"
    description = (
        "Place the order after the customer has seen the quote and confirmed they "
        "want to proceed. Creates the order in a pending state for the team to "
        "action. Only call this once a quote has been shown and the user confirms."
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        from .. import orders

        draft = (
            session.order_drafts.filter(status=OrderDraft.STATUS_QUOTED)
            .order_by("-created_at")
            .first()
        )
        # Confirmation gate: without a server-computed quote there is nothing to
        # place. This is what stops the model from conjuring an order/price.
        if draft is None:
            return ToolResult(
                ok=True,
                data={"created": False, "reason": "no_quote"},
                summary=(
                    "I don't have a confirmed quote yet. Let's finish the details and "
                    "I'll price it up before we place anything."
                ),
            )

        # Place it: backend (system of record) or local, deterministic money.
        outcome = orders.place_order(session, draft)
        if not outcome.get("created"):
            reason = outcome.get("reason", "no_quote")
            # A user-scoped placement needs a signed-in visitor: deep-link to login.
            if reason == "not_authenticated":
                from .. import sitemap

                dest = sitemap.resolve("signin")
                return ToolResult(
                    ok=True,
                    data={"created": False, "reason": reason, "action": "navigate",
                          "path": dest.path, "label": dest.label},
                    summary=(
                        "You'll need to sign in before I can place the order — I'll point "
                        "you to the sign-in page, then say 'confirm' again and we're set."
                    ),
                )
            return ToolResult(
                ok=True,
                data={"created": False, "reason": reason},
                summary=(
                    "I couldn't place that just now — the quote may have expired. "
                    "Let's re-check the details and I'll price it again before we place it."
                ),
            )

        draft.status = OrderDraft.STATUS_PLACED
        draft.save(update_fields=["status"])

        ref = outcome.get("ref") or outcome.get("order_id", "")[:8]
        amount = int(Decimal(outcome.get("amount") or "0"))
        label = outcome.get("label", "order")
        return ToolResult(
            ok=True,
            data={
                "created": True,
                "order_id": outcome.get("order_id", ""),
                "ref": ref,
                "status": outcome.get("status", "pending"),
            },
            summary=(
                f"Done — your {label.lower()} order is placed (ref {ref}) "
                f"for {outcome.get('currency', 'KES')} {amount:,}, pending with the team. "
                "They'll be in touch to finalise payment."
            ),
        )
