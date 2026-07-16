"""Identity resolution against the UrbanTrends host site (proposal §5 — login).

Mika is an **embedded helper agent**, not an auth provider. She never registers
users, never issues or checks codes, and keeps no user table of her own. She only
*verifies* whether the visitor is already signed in on urbantrends.dev and reuses
that identity — the site's django-allauth stack stays the single source of truth.

The host site is a headless allauth client (passkey / email-code, session-cookie
based). The browser never calls this agent directly; the site's proxy forwards
the request — carrying the `sessionid` cookie — and this module introspects
allauth's headless session endpoint to resolve the signed-in user. A raw client
claim is never trusted; the cookie is verified against allauth.

Pluggable behind one interface (same seam pattern as the planner/OTP), selected
by env with a keyless dev/test default:
  IDENTITY_BACKEND = "stub" (dev/tests, no network) | "allauth" (real)
  ALLAUTH_BASE_URL = host site base, e.g. https://urbantrends.dev
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Identity:
    """A verified host-site customer. `customer_ref` is a stable id (email/username)."""

    customer_ref: str
    display: str = ""


class StubIdentityProvider:
    """Keyless dev/test provider — no network, deterministic.

    Trusts an explicit `identity_hint` (the `X-UT-Identity` header the dev demo /
    tests set) so flows can exercise a "signed-in" visitor without a real allauth.
    Never selected when a real ALLAUTH_BASE_URL is configured.
    """

    def resolve(self, *, session_cookie: str | None, identity_hint: str | None) -> Identity | None:
        ref = (identity_hint or "").strip()
        return Identity(customer_ref=ref, display=ref) if ref else None


class AllauthIdentityProvider:
    """Verify the visitor by introspecting allauth's headless session endpoint.

    Forwards the host `sessionid` cookie to `GET /_allauth/browser/v1/auth/session`.
    allauth answers with `meta.is_authenticated` + `data.user` when signed in, or
    401 when not. We read only what allauth vouches for; we mint nothing.
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/") + "/_allauth/browser/v1/auth/session"

    def resolve(self, *, session_cookie: str | None, identity_hint: str | None) -> Identity | None:
        if not session_cookie:
            return None
        req = urllib.request.Request(
            self._url,
            headers={"Cookie": f"sessionid={session_cookie}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 401:  # 401 = simply not signed in; anything else is odd
                log.warning("allauth session introspection returned %s", exc.code)
            return None
        except Exception:  # network hiccup → treat as anonymous, never a 500
            log.exception("allauth session introspection failed")
            return None

        if not payload.get("meta", {}).get("is_authenticated"):
            return None
        user = payload.get("data", {}).get("user") or {}
        ref = str(user.get("email") or user.get("username") or user.get("id") or "")
        if not ref:
            return None
        return Identity(customer_ref=ref, display=str(user.get("display") or ref))


def get_identity_provider():
    """Return the active identity provider based on configuration."""
    backend = getattr(settings, "IDENTITY_BACKEND", "stub")
    base = getattr(settings, "ALLAUTH_BASE_URL", "")
    if backend == "allauth" and base:
        try:
            return AllauthIdentityProvider(base)
        except Exception:  # pragma: no cover - defensive; degrade to anonymous
            log.exception("Failed to init AllauthIdentityProvider; falling back to stub")
    return StubIdentityProvider()
