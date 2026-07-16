"""Backend integration (BACKEND_APIS.md): with URBANTRENDS_API_BASE set, Mica
sources catalog + pricing from the live backend and delegates order placement to
it (system of record), while the deterministic-money and audit guardrails hold.

All tests use a fake backend client — no network. The static path is covered by
test_order.py / test_pricing.py, which run with the backend off.
"""
import pytest

from agent import catalog, pricing
from agent.backend import BackendError
from agent.loop import handle_message, submit_order_form
from agent.models import Order, Session, Ticket

pytestmark = pytest.mark.django_db

_SERVICES = [
    {
        "key": "landing_page",
        "label": "Landing page",
        "description": "A marketing site.",
        "aliases": ["landing page", "website"],
        "form": {
            "service": "landing_page",
            "title": "Landing page — project brief",
            "fields": [
                {"name": "pages", "type": "integer", "label": "Pages",
                 "required": True, "min": 1, "max": 8, "default": 1},
                {"name": "copywriting", "type": "boolean", "label": "Copywriting?", "default": False},
                {"name": "cms", "type": "boolean", "label": "CMS?", "default": False},
                {"name": "rush", "type": "boolean", "label": "Rush?", "default": False},
            ],
        },
    }
]


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.quote_response = {
            "quote_id": "q_123", "currency": "KES", "amount": "45000",
            "breakdown": [{"label": "Base landing page", "amount": "45000"}],
        }
        self.order_response = {
            "order_id": "ord_9", "ref": "UT-ORD-9", "status": "pending",
            "currency": "KES", "amount": "45000",
        }
        self.raise_on_quote = None
        self.raise_on_order = None

    def get_json(self, path, *, session_cookie=None):
        self.calls.append(("GET", path, None, session_cookie, None))
        if path == "/services":
            return {"services": _SERVICES}
        raise AssertionError(f"unexpected GET {path}")

    def post_json(self, path, body, *, session_cookie=None, idempotency_key=None):
        self.calls.append(("POST", path, body, session_cookie, idempotency_key))
        if path.endswith("/quote"):
            if self.raise_on_quote:
                raise self.raise_on_quote
            return self.quote_response
        if path == "/orders":
            if self.raise_on_order:
                raise self.raise_on_order
            return self.order_response
        raise AssertionError(f"unexpected POST {path}")


@pytest.fixture
def backend(monkeypatch):
    """Turn the backend on, wired to a fake client; isolate the catalog cache."""
    from django.conf import settings

    from agent import backend as backend_mod

    fake = FakeBackend()
    monkeypatch.setattr(settings, "URBANTRENDS_API_BASE", "http://test")
    monkeypatch.setattr(backend_mod, "get_client", lambda: fake)
    catalog._http_cache.clear()
    yield fake
    catalog._http_cache.clear()


def test_client_builds_prefixed_url_and_auth(monkeypatch):
    """BackendClient adds /api/v1/agent and the bearer header; base may include it."""
    from agent import backend as backend_mod

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return FakeResp()

    monkeypatch.setattr(backend_mod.urllib.request, "urlopen", fake_urlopen)

    client = backend_mod.BackendClient("https://urbantrends.dev/", "secret", "Authorization", "Bearer ", 4)
    assert client.get_json("/services") == {"ok": True}
    assert captured["url"] == "https://urbantrends.dev/api/v1/agent/services"
    assert captured["headers"].get("Authorization") == "Bearer secret"

    # A base that already carries the prefix isn't doubled.
    client2 = backend_mod.BackendClient("https://urbantrends.dev/api/v1/agent", "k", "Authorization", "Bearer ", 4)
    client2.get_json("/sitemap")
    assert captured["url"] == "https://urbantrends.dev/api/v1/agent/sitemap"


def test_catalog_sourced_from_backend(backend):
    assert catalog.keys() == ["landing_page"]
    svc = catalog.get("landing_page")
    assert svc.label == "Landing page"
    assert [f["name"] for f in svc.form_fields] == ["pages", "copywriting", "cms", "rush"]
    # start_order's tool spec advertises the backend's service keys to the model.
    from agent.tools import registry
    spec = registry.get("start_order").spec()
    assert spec["input_schema"]["properties"]["service"]["enum"] == ["landing_page"]


def test_quote_comes_from_backend_with_quote_id(backend):
    q = pricing.quote("landing_page", {"pages": 2, "copywriting": True, "cms": False, "rush": False})
    assert str(q.amount) == "45000"
    assert q.quote_id == "q_123"
    assert q.as_dict()["quote_id"] == "q_123"
    assert backend.calls[-1][0:2] == ("POST", "/services/landing_page/quote")


def test_submit_form_stores_backend_quote(backend):
    session = Session.objects.create()
    handle_message(session, "I want to order a landing page")   # start_order (backend catalog)
    result = submit_order_form(session, {"pages": 2, "copywriting": True, "cms": False, "rush": False})

    assert result.action["quote"]["amount"] == "45000"
    draft = session.order_drafts.get()
    assert draft.status == draft.STATUS_QUOTED
    assert draft.quote["quote_id"] == "q_123"


def test_create_order_delegates_to_backend(backend):
    session = Session.objects.create()
    session._ut_session_cookie = "cookie-xyz"
    handle_message(session, "I want to order a landing page")
    submit_order_form(session, {"pages": 2, "copywriting": True, "cms": False, "rush": False})
    draft = session.order_drafts.get()

    confirm = handle_message(session, "confirm")

    assert confirm.action["created"] is True
    assert confirm.action["ref"] == "UT-ORD-9"
    assert "UT-ORD-9" in confirm.reply
    # Delegated fully: no local Order row, draft marked placed.
    assert Order.objects.count() == 0
    assert session.order_drafts.get().status == draft.STATUS_PLACED
    # POST /orders carried the quote_id, per-draft idempotency key, and session.
    post = [c for c in backend.calls if c[1] == "/orders"][0]
    _, _, body, cookie, idem = post
    assert body == {"quote_id": "q_123"}
    assert cookie == "cookie-xyz"
    assert idem == str(draft.id)


def test_backend_price_failure_becomes_form_error(backend):
    backend.raise_on_quote = BackendError("quote_unavailable", status=422)
    session = Session.objects.create()
    handle_message(session, "order a landing page")
    from agent.forms import FormError
    with pytest.raises(FormError):
        submit_order_form(session, {"pages": 1})


def test_order_requires_sign_in(backend):
    """A user-scoped 401 becomes a sign-in prompt, not an escalation."""
    backend.raise_on_order = BackendError("not_authenticated", status=401)
    session = Session.objects.create()
    handle_message(session, "order a landing page")
    submit_order_form(session, {"pages": 1})

    result = handle_message(session, "confirm")

    assert result.escalated is False
    assert result.action["created"] is False
    assert result.action["reason"] == "not_authenticated"
    assert result.action["action"] == "navigate"
    assert result.action["path"] == "/login"
    assert Order.objects.count() == 0
    assert not Ticket.objects.exists()


def test_order_provider_outage_escalates(backend):
    """A backend outage on placement is a failure → loop retries then escalates."""
    backend.raise_on_order = BackendError("backend_unreachable")
    session = Session.objects.create()
    handle_message(session, "order a landing page")
    submit_order_form(session, {"pages": 1})

    result = handle_message(session, "confirm")

    assert result.escalated is True
    assert Order.objects.count() == 0
    assert Ticket.objects.filter(reason=Ticket.REASON_VERIFY_EXHAUSTED).exists()
