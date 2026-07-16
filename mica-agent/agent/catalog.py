"""Service catalog: what UrbanTrends sells, the info needed to quote it, and the
deterministic pricing rule for each (proposal §5 ordering, §8 deterministic money).

The catalog is the single source of truth for three things the model must never
control: (1) which services exist, (2) the dynamic form schema shown to collect
requirements, and (3) the pricing rule. The LLM only gathers requirements and
picks a service key; every price comes from the `price` rule here.

Amounts are in Kenyan shillings (KES), as whole Decimals.

NOTE (future — see PROPOSAL §12 "Backend pricing integration"): the rates below
are illustrative pilot figures held in code. When the tool is wired to the
company's real pricing backend, `price` should read the company's live prices
instead of these constants. The deterministic-money guardrail is unchanged — the
number's *source* moves to the backend, but it is still server-side truth that
the model never sets, and `agent/pricing.py` stays the sole engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

CURRENCY = "KES"


@dataclass(frozen=True)
class LineItem:
    label: str
    amount: Decimal


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    description: str
    # Free-text aliases so the keyless stub planner can map intent → service.
    aliases: tuple[str, ...]
    # JSONB-friendly dynamic form schema rendered by the widget (proposal §5).
    form_fields: tuple[dict, ...]
    # Deterministic pricing rule: cleaned params → itemised breakdown. None for
    # services sourced from the backend, where pricing is remote (POST /quote).
    price: Callable[[dict], list[LineItem]] | None = field(default=None, repr=False)

    def form_schema(self) -> dict:
        return {
            "service": self.key,
            "title": f"{self.label} — project brief",
            "fields": [dict(f) for f in self.form_fields],
        }


def _rush(items: list[LineItem], rate: str, label: str) -> None:
    """Append a percentage surcharge on the running subtotal, in place."""
    subtotal = sum((i.amount for i in items), Decimal("0"))
    surcharge = (subtotal * Decimal(rate)).quantize(Decimal("1"))
    items.append(LineItem(label, surcharge))


def _landing_price(p: dict) -> list[LineItem]:
    items = [LineItem("Base landing page", Decimal("25000"))]
    if p["pages"] > 1:
        items.append(LineItem(f"Extra pages ×{p['pages'] - 1}", Decimal("8000") * (p["pages"] - 1)))
    if p["copywriting"]:
        items.append(LineItem("Copywriting", Decimal("12000")))
    if p["cms"]:
        items.append(LineItem("CMS / editable content", Decimal("15000")))
    if p["rush"]:
        _rush(items, "0.25", "Rush delivery (25%)")
    return items


def _webapp_price(p: dict) -> list[LineItem]:
    items = [LineItem("Base web application", Decimal("120000"))]
    if p["auth"]:
        items.append(LineItem("User accounts & auth", Decimal("30000")))
    if p["integrations"] > 0:
        items.append(
            LineItem(f"Integrations ×{p['integrations']}", Decimal("15000") * p["integrations"])
        )
    if p["timeline_weeks"] < 4:
        _rush(items, "0.20", "Accelerated timeline (20%)")
    return items


def _maintenance_price(p: dict) -> list[LineItem]:
    tiers = {"basic": Decimal("15000"), "standard": Decimal("30000"), "premium": Decimal("55000")}
    tier = p["tier"]
    return [LineItem(f"Maintenance retainer — {tier}", tiers[tier])]


SERVICES: dict[str, Service] = {
    s.key: s
    for s in [
        Service(
            key="landing_page",
            label="Landing page",
            description="A marketing site / landing page.",
            aliases=("landing page", "landing", "website", "web site", "marketing site", "site"),
            form_fields=(
                {"name": "pages", "type": "integer", "label": "Number of pages",
                 "required": True, "min": 1, "max": 8, "default": 1},
                {"name": "copywriting", "type": "boolean", "label": "Need copywriting?",
                 "default": False},
                {"name": "cms", "type": "boolean", "label": "CMS / editable content?",
                 "default": False},
                {"name": "rush", "type": "boolean", "label": "Rush (2-week) delivery?",
                 "default": False},
            ),
            price=_landing_price,
        ),
        Service(
            key="web_app",
            label="Web application",
            description="A custom web application.",
            aliases=("web app", "web application", "application", "app", "platform", "portal", "saas"),
            form_fields=(
                {"name": "auth", "type": "boolean", "label": "User accounts / login?",
                 "default": True},
                {"name": "integrations", "type": "integer", "label": "Third-party integrations",
                 "required": True, "min": 0, "max": 10, "default": 0},
                {"name": "timeline_weeks", "type": "integer", "label": "Desired timeline (weeks)",
                 "required": True, "min": 1, "max": 52, "default": 8},
            ),
            price=_webapp_price,
        ),
        Service(
            key="maintenance",
            label="Maintenance retainer",
            description="Monthly maintenance & support.",
            aliases=("maintenance", "retainer", "support plan", "upkeep"),
            form_fields=(
                {"name": "tier", "type": "enum", "label": "Support tier", "required": True,
                 "options": ["basic", "standard", "premium"], "default": "standard"},
            ),
            price=_maintenance_price,
        ),
    ]
}


# ── Provider seam (BACKEND_APIS.md) ──────────────────────────────────────────
# The catalog is either the static SERVICES above (keyless dev/test default) or
# the live urbantrends.dev backend when URBANTRENDS_API_BASE is set. Same shape
# either way; call sites use the module-level get() / keys() / match_text().


def _match(services: dict[str, Service], text: str) -> Service | None:
    """Best-effort free text → service (stub planner only). Longest alias wins."""
    lowered = text.lower()
    best: tuple[int, Service] | None = None
    for svc in services.values():
        for alias in svc.aliases:
            if alias in lowered and (best is None or len(alias) > best[0]):
                best = (len(alias), svc)
    return best[1] if best else None


class _StaticCatalog:
    def all(self) -> dict[str, Service]:
        return SERVICES


def _service_from_json(s: dict) -> Service:
    """Build a Service from the backend's /services payload (pricing is remote)."""
    form = s.get("form") or {}
    return Service(
        key=s["key"],
        label=s.get("label", s["key"]),
        description=s.get("description", ""),
        aliases=tuple(s.get("aliases", ())),
        form_fields=tuple(dict(f) for f in form.get("fields", [])),
        price=None,  # money comes from POST /services/{key}/quote, not here
    )


class _HttpCatalog:
    """Fetches the live catalog, cached briefly (services change rarely)."""

    _TTL = 60.0  # seconds

    def __init__(self, client) -> None:
        self._client = client
        self._cache: dict[str, Service] | None = None
        self._at = 0.0

    def all(self) -> dict[str, Service]:
        import time

        now = time.monotonic()
        if self._cache is not None and now - self._at < self._TTL:
            return self._cache
        data = self._client.get_json("/services")
        self._cache = {s["key"]: _service_from_json(s) for s in data.get("services", [])}
        self._at = now
        return self._cache


_STATIC = _StaticCatalog()
_http_cache: dict[str, _HttpCatalog] = {}


def _provider():
    from django.conf import settings

    base = getattr(settings, "URBANTRENDS_API_BASE", "")
    if not base:
        return _STATIC
    prov = _http_cache.get(base)
    if prov is None:
        from .backend import get_client

        prov = _HttpCatalog(get_client())
        _http_cache[base] = prov
    return prov


def get(service_key: str) -> Service:
    svc = _provider().all().get(service_key)
    if svc is None:
        raise KeyError(f"unknown service: {service_key!r}")
    return svc


def keys() -> list[str]:
    return list(_provider().all())


def match_text(text: str) -> Service | None:
    """Best-effort free text → service, for the keyless stub planner only."""
    return _match(_provider().all(), text)
