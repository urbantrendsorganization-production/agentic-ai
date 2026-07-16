"""P1 gate at the HTTP boundary: the widget's create-session + post-message flow."""
import pytest
from rest_framework.test import APIClient

from agent.models import AgentEvent, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def test_health(client):
    resp = client.get("/api/health/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_session_and_message(client):
    resp = client.post("/api/sessions/")
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    resp = client.post(
        f"/api/sessions/{session_id}/messages/",
        {"text": "hi mika"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "hi mika"
    assert body["escalated"] is False

    session = Session.objects.get(id=session_id)
    assert session.events.filter(step=AgentEvent.STEP_RESPOND).count() == 1


def test_message_requires_text(client):
    session_id = client.post("/api/sessions/").json()["id"]
    resp = client.post(f"/api/sessions/{session_id}/messages/", {}, format="json")
    assert resp.status_code == 400
