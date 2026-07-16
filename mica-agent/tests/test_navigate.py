"""P2 gate — deep-link navigation through the loop and the tool directly."""
import pytest

from agent.loop import handle_message
from agent.models import AgentEvent, Session
from agent.tools.navigate import NavigateTool

pytestmark = pytest.mark.django_db


def test_navigation_intent_returns_deep_link():
    session = Session.objects.create()
    result = handle_message(session, "where do I find your pricing?")

    assert "/pricing" in result.reply
    verify = session.events.filter(step=AgentEvent.STEP_VERIFY).latest("seq")
    assert verify.payload["ok"] is True
    assert verify.payload["result"]["action"] == "navigate"
    assert verify.payload["result"]["path"] == "/pricing"


def test_navigate_tool_rejects_unknown_destination():
    tool = NavigateTool()
    with pytest.raises(ValueError):
        tool.validate({"destination": "https://evil.example.com"})


def test_navigate_enum_matches_sitemap():
    # The model is only ever offered whitelisted destinations. spec() is the
    # contract sent to Claude; it reflects the active sitemap (static or backend).
    from agent import sitemap

    assert set(NavigateTool().spec()["input_schema"]["properties"]["destination"]["enum"]) == set(
        sitemap.keys()
    )


def test_registry_exposes_account_and_navigation_tools():
    from agent.tools import registry

    # Subset check so later phases can add tools without churning this test.
    assert {"check_login", "navigate"} <= set(registry.names())
    # Mika no longer runs her own OTP login (host allauth owns auth).
    assert "request_login_code" not in registry.names()
    assert "verify_login_code" not in registry.names()
