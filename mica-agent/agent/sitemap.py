"""Read-only site map for deep-link navigation (proposal §5).

A whitelist, deliberately: the `navigate` tool can only ever send a visitor to a
destination that appears here, so the model can never deep-link to an arbitrary
or hostile URL. `aliases` help the keyless stub planner map free-text intents
("where do I find your prices?") onto a destination key.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Destination:
    key: str
    path: str
    label: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Keep in sync with the urbantrends.dev route table. Paths are site-relative;
# the widget resolves them against the current origin and navigates client-side.
DESTINATIONS: dict[str, Destination] = {
    d.key: d
    for d in [
        Destination("home", "/", "Home", ("home", "start", "landing")),
        Destination("services", "/services", "Services", ("services", "what you do", "offerings")),
        Destination("pricing", "/pricing", "Pricing", ("pricing", "price", "prices", "cost", "quote", "plans")),
        Destination("portfolio", "/portfolio", "Portfolio", ("portfolio", "work", "projects", "case studies")),
        Destination("contact", "/contact", "Contact", ("contact", "reach", "get in touch", "email us")),
        Destination("about", "/about", "About", ("about", "who you are", "team", "company")),
        Destination("orders", "/account/orders", "Your orders", ("orders", "my orders", "order history")),
    ]
}


def resolve(key: str) -> Destination | None:
    return DESTINATIONS.get(key)


def keys() -> list[str]:
    return list(DESTINATIONS)


def match_text(text: str) -> Destination | None:
    """Best-effort map free text onto a destination via key/alias substring.

    Used only by the keyless stub planner; real Claude picks the destination
    directly through tool use.
    """
    lowered = text.lower()
    for dest in DESTINATIONS.values():
        if dest.key in lowered or any(alias in lowered for alias in dest.aliases):
            return dest
    return None
