"""The deterministic pricing rules engine (proposal §8 — deterministic money).

Pure and side-effect free: same params in → same quote out, every time. The
model never runs through here with authority; it only supplies the service key
and (validated) requirement params. All arithmetic and every shilling comes from
the catalog's rules, so a quote is fully reproducible and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from . import catalog


@dataclass(frozen=True)
class Quote:
    currency: str
    amount: Decimal
    breakdown: list[dict]  # [{"label": str, "amount": "12345"}], JSON-friendly
    # Backend-issued id the order endpoint references to look up the amount
    # server-side (empty for the local static engine, which has no persisted id).
    quote_id: str = ""

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "amount": str(self.amount),
            "breakdown": self.breakdown,
            "quote_id": self.quote_id,
        }

    def summary(self) -> str:
        lines = [f"  • {i['label']}: {self.currency} {int(i['amount']):,}" for i in self.breakdown]
        body = "\n".join(lines)
        return f"{body}\n  = Total: {self.currency} {int(self.amount):,}"


def quote(service_key: str, params: dict, *, session=None) -> Quote:
    """Compute the quote for a service given already-validated params.

    Deterministic money either way: with URBANTRENDS_API_BASE set the price comes
    from the backend's server-side engine (POST /services/{key}/quote); otherwise
    from the in-repo static rules. The model never sets an amount in either path.
    """
    from django.conf import settings

    if getattr(settings, "URBANTRENDS_API_BASE", ""):
        return _backend_quote(service_key, params, session)
    return _static_quote(service_key, params)


def _static_quote(service_key: str, params: dict) -> Quote:
    service = catalog.get(service_key)
    items = service.price(params)
    total = sum((i.amount for i in items), Decimal("0"))
    breakdown = [{"label": i.label, "amount": str(i.amount)} for i in items]
    return Quote(currency=catalog.CURRENCY, amount=total, breakdown=breakdown)


def _backend_quote(service_key: str, params: dict, session) -> Quote:
    from .backend import get_client

    cookie = getattr(session, "_ut_session_cookie", None) if session is not None else None
    data = get_client().post_json(
        f"/services/{service_key}/quote", {"params": params}, session_cookie=cookie
    )
    return Quote(
        currency=data["currency"],
        amount=Decimal(str(data["amount"])),
        breakdown=list(data.get("breakdown", [])),
        quote_id=str(data.get("quote_id", "")),
    )
