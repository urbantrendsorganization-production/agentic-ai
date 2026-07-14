"""P2 gate — OTP login end-to-end through the loop (keyless stub planner)."""
import datetime as dt

import pytest
from django.utils import timezone

from agent import otp
from agent.loop import handle_message
from agent.models import LoginChallenge, Session

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_outbox():
    otp.CONSOLE_OUTBOX.clear()
    yield
    otp.CONSOLE_OUTBOX.clear()


def _last_code():
    return otp.CONSOLE_OUTBOX[-1]["code"]


def test_request_code_creates_challenge_and_sends():
    session = Session.objects.create()
    result = handle_message(session, "log me in, my email is edwin@urbantrends.dev")

    assert result.escalated is False
    challenge = session.challenges.get()
    assert challenge.channel == "email"
    assert challenge.destination == "edwin@urbantrends.dev"
    assert challenge.consumed_at is None
    # Code was "sent" but only ever stored hashed.
    assert otp.CONSOLE_OUTBOX and otp.CONSOLE_OUTBOX[-1]["destination"] == "edwin@urbantrends.dev"
    assert challenge.code_hash and challenge.code_hash != _last_code()
    # Reply masks the destination — never leaks the full address or the code.
    assert "***" in result.reply and _last_code() not in result.reply


def test_full_login_flow_binds_customer_ref():
    session = Session.objects.create()
    handle_message(session, "sign in with edwin@urbantrends.dev")
    result = handle_message(session, _last_code())

    session.refresh_from_db()
    assert session.customer_ref == "edwin@urbantrends.dev"
    assert "signed in" in result.reply.lower()
    assert session.challenges.get().consumed_at is not None


def test_wrong_code_reports_but_does_not_escalate_or_bind():
    session = Session.objects.create()
    handle_message(session, "log in with +254700111222")
    result = handle_message(session, "000000" if _last_code() != "000000" else "111111")

    session.refresh_from_db()
    assert session.customer_ref == ""          # not logged in
    assert result.escalated is False           # a wrong code is not a failure
    assert "didn't match" in result.reply
    assert session.challenges.get().attempts == 1


def test_expired_code_is_rejected():
    session = Session.objects.create()
    handle_message(session, "phone login +254700111222")
    code = _last_code()
    LoginChallenge.objects.filter(session=session).update(
        expires_at=timezone.now() - dt.timedelta(minutes=1)
    )

    result = handle_message(session, code)
    session.refresh_from_db()
    assert session.customer_ref == ""
    assert "expired" in result.reply.lower() or "fresh code" in result.reply.lower()


def test_requesting_new_code_retires_old_challenge():
    session = Session.objects.create()
    handle_message(session, "email me at a@b.com")
    handle_message(session, "actually use c@d.com instead a@b.com")

    active = session.challenges.filter(consumed_at__isnull=True)
    assert active.count() == 1
    assert active.get().destination == "c@d.com"


def test_send_failure_escalates(monkeypatch):
    class DeadSender:
        def send(self, **kwargs):
            return False

    monkeypatch.setattr("agent.tools.login.get_sender", lambda: DeadSender())
    session = Session.objects.create()
    result = handle_message(session, "log in with edwin@urbantrends.dev")

    # A real delivery failure exhausts retries and escalates to a human.
    assert result.escalated is True
