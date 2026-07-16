"""P6 — per-session / per-IP rate limiting at the HTTP boundary (proposal §8)."""
import pytest
from rest_framework.test import APIClient

from agent.ratelimit import allow

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def test_allow_counts_within_a_window(settings):
    settings.RATE_LIMIT_ENABLED = True
    ok = [allow("t", "k", limit=3, window=60)[0] for _ in range(4)]
    assert ok == [True, True, True, False]


def test_allow_fails_open_when_disabled(settings):
    settings.RATE_LIMIT_ENABLED = False
    assert all(allow("t", "k", limit=1, window=60)[0] for _ in range(5))


def test_message_rate_limit_returns_429(client, settings):
    settings.RATE_LIMIT_SESSION_MESSAGES_PER_MINUTE = 2
    sid = client.post("/api/sessions/").json()["id"]

    for _ in range(2):
        assert client.post(
            f"/api/sessions/{sid}/messages/", {"text": "hi"}, format="json"
        ).status_code == 200

    blocked = client.post(f"/api/sessions/{sid}/messages/", {"text": "hi"}, format="json")
    assert blocked.status_code == 429
    assert blocked["Retry-After"]
    assert blocked.json()["retry_after"] >= 0


def test_session_creation_rate_limited_per_ip(client, settings):
    settings.RATE_LIMIT_IP_SESSIONS_PER_MINUTE = 2
    codes = [client.post("/api/sessions/").status_code for _ in range(3)]
    assert codes == [201, 201, 429]
