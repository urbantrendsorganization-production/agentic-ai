"""P2 (revised) — login is a *host-site* auth check, not an agent-run OTP flow.

Mika verifies the visitor's urbantrends.dev session (agent/identity.py) and reuses
that identity; she never registers users or issues codes. The keyless stub
provider trusts an X-UT-Identity header so these flows run with no network.
"""
import pytest
from rest_framework.test import APIClient

from agent.identity import Identity, StubIdentityProvider
from agent.loop import handle_message
from agent.models import Session
from agent.tools.account import CheckLoginTool

pytestmark = pytest.mark.django_db


def test_stub_provider_resolves_from_hint():
    p = StubIdentityProvider()
    assert p.resolve(session_cookie=None, identity_hint="edwin@urbantrends.dev") == Identity(
        customer_ref="edwin@urbantrends.dev", display="edwin@urbantrends.dev"
    )
    # No hint / no session → anonymous.
    assert p.resolve(session_cookie=None, identity_hint=None) is None
    assert p.resolve(session_cookie="sess", identity_hint="  ") is None


def test_session_creation_binds_verified_host_identity():
    client = APIClient()
    resp = client.post("/api/sessions/", HTTP_X_UT_IDENTITY="edwin@urbantrends.dev")
    assert resp.status_code == 201
    assert resp.json()["customer_ref"] == "edwin@urbantrends.dev"

    session = Session.objects.get(id=resp.json()["id"])
    assert session.customer_ref == "edwin@urbantrends.dev"


def test_anonymous_session_has_blank_customer_ref():
    client = APIClient()
    resp = client.post("/api/sessions/")
    assert resp.status_code == 201
    assert resp.json()["customer_ref"] == ""


def test_message_upgrades_anonymous_session_when_visitor_signs_in():
    # The widget persists a session across the /login round-trip, so a visitor can
    # sign in *after* the session began. A later message must upgrade the session
    # from anonymous to the now-verified identity (view._refresh_identity).
    client = APIClient()
    sid = client.post("/api/sessions/").json()["id"]  # created anonymous
    assert Session.objects.get(id=sid).customer_ref == ""

    # Same session, but now the host reports a signed-in visitor.
    resp = client.post(
        f"/api/sessions/{sid}/messages/",
        {"text": "hello"},
        format="json",
        HTTP_X_UT_IDENTITY="edwin@urbantrends.dev",
    )
    assert resp.status_code == 200
    assert Session.objects.get(id=sid).customer_ref == "edwin@urbantrends.dev"


def test_check_login_reports_signed_in():
    session = Session.objects.create(customer_ref="edwin@urbantrends.dev")
    result = CheckLoginTool().run({}, session=session)
    assert result.data["signed_in"] is True
    assert result.data["customer_ref"] == "edwin@urbantrends.dev"
    assert "edwin@urbantrends.dev" in result.summary


def test_check_login_points_anonymous_visitor_to_signin():
    session = Session.objects.create()  # anonymous
    result = CheckLoginTool().run({}, session=session)
    assert result.data["signed_in"] is False
    # Deep-links to the host site's sign-in page — Mika never collects credentials.
    assert result.data["action"] == "navigate"
    assert result.data["path"] == "/login"


def test_login_intent_routes_to_check_login_not_otp():
    session = Session.objects.create()
    result = handle_message(session, "am I signed in?")
    # Anonymous → check_login hands back a navigate-to-signin action.
    assert result.action["signed_in"] is False
    assert result.action["path"] == "/login"
