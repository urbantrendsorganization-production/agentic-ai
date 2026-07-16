"""Customer profile enrichment (GET /api/v1/agent/customers/me).

Optional polish over the identity check: when the backend is configured and the
visitor is signed in, fetch their display name + open-order count so Mika can
greet them warmly. Purely additive and best-effort — any failure (anonymous,
401, backend down) returns None and the caller falls back to the bare identity.
"""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger(__name__)


def fetch_me(session) -> dict | None:
    """Return {id, email, display, open_orders} for the signed-in visitor, or None."""
    if not getattr(settings, "URBANTRENDS_API_BASE", ""):
        return None
    cookie = getattr(session, "_ut_session_cookie", None)
    if not cookie:  # user-scoped: no forwarded session → nothing to resolve
        return None
    from .backend import BackendError, get_client

    try:
        return get_client().get_json("/customers/me", session_cookie=cookie)
    except BackendError:  # 401 / down → skip enrichment, never fail the turn
        return None
    except Exception:  # pragma: no cover - defensive; enrichment must never 500
        log.exception("customers/me enrichment failed")
        return None
