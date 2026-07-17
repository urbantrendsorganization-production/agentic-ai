"""HTTP surface for the agent (P1: create session, post a message).

The widget talks to these endpoints; WebSocket/SSE streaming is a P2 concern.
"""
from __future__ import annotations

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .forms import FormError
from .identity import get_identity_provider
from .loop import handle_message, submit_order_form
from .models import Session
from .ratelimit import allow, client_ip
from .serializers import MessageInSerializer, SessionSerializer


def _rate_limited(bucket: str, key: str, limit: int):
    """Return a 429 Response if (bucket, key) is over `limit`/min, else None."""
    ok, retry = allow(bucket, key, limit=limit, window=60)
    if ok:
        return None
    resp = Response(
        {"detail": "Too many requests — please slow down.", "retry_after": retry},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    resp["Retry-After"] = str(retry)
    return resp


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def whoami(request):
    """Auth diagnostic: does the visitor's login actually reach Mica?

    Everything user-scoped (placing an order, "my orders") authenticates from the
    forwarded `sessionid` cookie — if it's missing or anonymous the backend returns
    401 not_authenticated and Mika keeps deep-linking to /login. Open this same-
    origin (https://urbantrends.dev/agent/api/whoami) while signed in:

      * cookie_present=false → the login didn't set a `sessionid` cookie on this
        origin (allauth/proxy/cookie-domain issue — the browser never sends it).
      * cookie_present=true but authenticated=false → the cookie reaches Mica but
        allauth won't vouch for it (wrong ALLAUTH_BASE_URL, or it's an anon session).
      * authenticated=true → Mika sees you signed in; the problem is elsewhere.

    Never leaks the cookie value — only its presence/length and the resolved ref.
    """
    cookie = request.COOKIES.get("sessionid")
    identity = get_identity_provider().resolve(
        session_cookie=cookie, identity_hint=request.headers.get("X-UT-Identity")
    )
    return Response({
        "cookie_present": bool(cookie),
        "cookie_len": len(cookie) if cookie else 0,
        "identity_backend": getattr(settings, "IDENTITY_BACKEND", "stub"),
        "allauth_base_url": getattr(settings, "ALLAUTH_BASE_URL", ""),
        "authenticated": identity is not None,
        "customer_ref": identity.customer_ref if identity else "",
    })


def widget_demo(request):
    """Serve the Mika widget demo host page (dev harness for P5)."""
    demo = settings.BASE_DIR / "widget" / "demo.html"
    if not demo.exists():  # pragma: no cover - defensive
        raise Http404("widget demo not built")
    return FileResponse(open(demo, "rb"), content_type="text/html")


@api_view(["POST"])
def create_session(request):
    limited = _rate_limited(
        "session", client_ip(request), settings.RATE_LIMIT_IP_SESSIONS_PER_MINUTE
    )
    if limited:
        return limited

    # Resolve the visitor's host-site identity by verifying their urbantrends.dev
    # session (agent/identity.py). Mika never authenticates anyone herself; an
    # anonymous visitor simply gets a blank customer_ref.
    identity = get_identity_provider().resolve(
        session_cookie=request.COOKIES.get("sessionid"),
        identity_hint=request.headers.get("X-UT-Identity"),
    )
    session = Session.objects.create(customer_ref=identity.customer_ref if identity else "")
    return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


def _refresh_identity(session, session_cookie, identity_hint):
    """Re-resolve the visitor's host identity and upgrade the session if it changed.

    Only writes when the resolved ref differs from what's stored — so an anonymous
    session becomes signed-in once the visitor logs in, without churning the DB on
    every turn. Never clears a known ref on a transient resolve miss (network blip).
    """
    identity = get_identity_provider().resolve(
        session_cookie=session_cookie, identity_hint=identity_hint
    )
    ref = identity.customer_ref if identity else ""
    if ref and ref != session.customer_ref:
        session.customer_ref = ref
        session.save(update_fields=["customer_ref"])


@api_view(["POST"])
def post_message(request, session_id):
    # Throttle per IP and per session before doing any work (proposal §8).
    limited = _rate_limited(
        "msg_ip", client_ip(request), settings.RATE_LIMIT_IP_MESSAGES_PER_MINUTE
    ) or _rate_limited(
        "msg_session", str(session_id), settings.RATE_LIMIT_SESSION_MESSAGES_PER_MINUTE
    )
    if limited:
        return limited

    session = get_object_or_404(Session, id=session_id)
    incoming = MessageInSerializer(data=request.data)
    incoming.is_valid(raise_exception=True)

    # Carry the visitor's host sessionid through the turn (transient, unsaved) so
    # user-scoped backend calls (e.g. placing an order) can forward X-UT-Session.
    cookie = request.COOKIES.get("sessionid")
    session._ut_session_cookie = cookie
    # Identity is resolved at session creation, but the widget persists a session
    # across page loads — so a visitor who signs in *after* the session began (e.g.
    # via the login deep-link mid-order) would otherwise stay anonymous forever.
    # Re-resolve each turn and upgrade customer_ref when it newly resolves/changes.
    _refresh_identity(session, cookie, request.headers.get("X-UT-Identity"))
    result = handle_message(session, incoming.validated_data["text"])
    return Response(
        {
            "reply": result.reply,
            "escalated": result.escalated,
            "events": result.events,
            "action": result.action,
        }
    )


@api_view(["POST"])
def order_form(request, session_id):
    """Submit a dynamic order form; returns the deterministic rules-engine quote."""
    limited = _rate_limited(
        "msg_session", str(session_id), settings.RATE_LIMIT_SESSION_MESSAGES_PER_MINUTE
    )
    if limited:
        return limited

    session = get_object_or_404(Session, id=session_id)
    session._ut_session_cookie = request.COOKIES.get("sessionid")
    try:
        result = submit_order_form(session, request.data)
    except FormError as exc:
        return Response({"errors": exc.errors}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "reply": result.reply,
            "action": result.action,
            "events": result.events,
        }
    )
