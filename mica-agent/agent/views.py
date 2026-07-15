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
from .serializers import MessageInSerializer, SessionSerializer


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def widget_demo(request):
    """Serve the Mika widget demo host page (dev harness for P5)."""
    demo = settings.BASE_DIR / "widget" / "demo.html"
    if not demo.exists():  # pragma: no cover - defensive
        raise Http404("widget demo not built")
    return FileResponse(open(demo, "rb"), content_type="text/html")


@api_view(["POST"])
def create_session(request):
    # Resolve the visitor's host-site identity by verifying their urbantrends.dev
    # session (agent/identity.py). Mika never authenticates anyone herself; an
    # anonymous visitor simply gets a blank customer_ref.
    identity = get_identity_provider().resolve(
        session_cookie=request.COOKIES.get("sessionid"),
        identity_hint=request.headers.get("X-UT-Identity"),
    )
    session = Session.objects.create(customer_ref=identity.customer_ref if identity else "")
    return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def post_message(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    incoming = MessageInSerializer(data=request.data)
    incoming.is_valid(raise_exception=True)

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
    session = get_object_or_404(Session, id=session_id)
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
