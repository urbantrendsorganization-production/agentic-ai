"""P6 — audit-trail review: a session is fully reconstructable from AgentEvent
alone (proposal success metric §10), via the reconstruct_session command.
"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from agent.loop import handle_message
from agent.models import Session

pytestmark = pytest.mark.django_db


def test_reconstruct_session_replays_the_loop():
    session = Session.objects.create(customer_ref="edwin@urbantrends.dev")
    handle_message(session, "hello")
    handle_message(session, "where is your pricing?")

    out = StringIO()
    call_command("reconstruct_session", str(session.id), stdout=out)
    dump = out.getvalue()

    assert "edwin@urbantrends.dev" in dump
    assert "receive" in dump and "act" in dump and "verify" in dump and "respond" in dump
    assert "gapless=True" in dump


def test_reconstruct_session_rejects_unknown_id():
    with pytest.raises(CommandError):
        call_command("reconstruct_session", "not-a-session")
