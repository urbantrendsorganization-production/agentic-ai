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
        Destination("signin", "/login", "Sign in", ("sign in", "log in", "signin", "login", "my account")),
    ]
}


# ── Provider seam (BACKEND_APIS.md) ──────────────────────────────────────────
# The destination whitelist is the static DESTINATIONS above (keyless dev/test
# default) or the live backend (GET /sitemap) when URBANTRENDS_API_BASE is set.
# navigate may only ever reach a key that appears here — the model can't add one.


class _StaticSitemap:
    def all(self) -> dict[str, Destination]:
        return DESTINATIONS


def _destination_from_json(d: dict) -> Destination:
    return Destination(
        key=d["key"],
        path=d["path"],
        label=d.get("label", d["key"]),
        aliases=tuple(d.get("aliases", ())),
    )


class _HttpSitemap:
    _TTL = 300.0  # seconds; routes change rarely

    def __init__(self, client) -> None:
        self._client = client
        self._cache: dict[str, Destination] | None = None
        self._at = 0.0

    def all(self) -> dict[str, Destination]:
        import time

        now = time.monotonic()
        if self._cache is not None and now - self._at < self._TTL:
            return self._cache
        data = self._client.get_json("/sitemap")
        self._cache = {d["key"]: _destination_from_json(d) for d in data.get("destinations", [])}
        self._at = now
        return self._cache


_STATIC = _StaticSitemap()
_http_cache: dict[str, _HttpSitemap] = {}


def _provider():
    from django.conf import settings

    base = getattr(settings, "URBANTRENDS_API_BASE", "")
    if not base:
        return _STATIC
    prov = _http_cache.get(base)
    if prov is None:
        from .backend import get_client

        prov = _HttpSitemap(get_client())
        _http_cache[base] = prov
    return prov


def resolve(key: str) -> Destination | None:
    return _provider().all().get(key)


def keys() -> list[str]:
    return list(_provider().all())


def paths() -> set[str]:
    """The set of whitelisted destination paths (for navigate's verify step)."""
    return {d.path for d in _provider().all().values()}


def match_text(text: str) -> Destination | None:
    """Best-effort map free text onto a destination via key/alias substring.

    Used only by the keyless stub planner; real Claude picks the destination
    directly through tool use.
    """
    lowered = text.lower()
    for dest in _provider().all().values():
        if dest.key in lowered or any(alias in lowered for alias in dest.aliases):
            return dest
    return None
