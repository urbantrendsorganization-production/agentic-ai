"""HTTP surface for the agent (P1: create session, post a message).

The widget talks to these endpoints; WebSocket/SSE streaming is a P2 concern.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .loop import handle_message
from .models import Session
from .serializers import MessageInSerializer, SessionSerializer


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
def create_session(request):
    session = Session.objects.create()
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
        }
    )
