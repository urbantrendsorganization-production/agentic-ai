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

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "amount": str(self.amount),
            "breakdown": self.breakdown,
        }

    def summary(self) -> str:
        lines = [f"  • {i['label']}: {self.currency} {int(i['amount']):,}" for i in self.breakdown]
        body = "\n".join(lines)
        return f"{body}\n  = Total: {self.currency} {int(self.amount):,}"


def quote(service_key: str, params: dict) -> Quote:
    """Compute the quote for a service given already-validated params."""
    service = catalog.get(service_key)
    items = service.price(params)
    total = sum((i.amount for i in items), Decimal("0"))
    breakdown = [{"label": i.label, "amount": str(i.amount)} for i in items]
    return Quote(currency=catalog.CURRENCY, amount=total, breakdown=breakdown)
