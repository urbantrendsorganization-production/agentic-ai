"""Backend integration (BACKEND_APIS.md): with URBANTRENDS_API_BASE set, Mica
sources catalog + pricing from the live backend and delegates order placement to
it (system of record), while the deterministic-money and audit guardrails hold.

All tests use a fake backend client — no network. The static path is covered by
test_order.py / test_pricing.py, which run with the backend off.
"""
import pytest

from agent import catalog, kb, pricing, sitemap
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


_KB = [
    {"key": "payment_methods", "title": "Payment methods",
     "answer": "We take M-Pesa or bank transfer once your order is confirmed.",
     "aliases": ["payment", "mpesa", "methods do you accept"]},
]
_SITEMAP = [
    {"key": "pricing", "path": "/pricing", "label": "Pricing", "aliases": ["pricing", "prices"]},
    {"key": "orders", "path": "/portal/orders", "label": "Your orders", "aliases": ["my orders"]},
    {"key": "signin", "path": "/login", "label": "Sign in", "aliases": ["sign in", "log in"]},
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
        self.ticket_response = {"ticket_id": "tkt_1", "ref": "UT-1", "status": "open"}
        self.orders_mine_response = {"orders": [
            {"ref": "UT-ORD-9", "service": "landing_page", "status": "active",
             "currency": "KES", "amount": "45000"},
        ]}
        self.customers_me_response = {
            "id": 42, "email": "amina@example.com", "display": "Amina W.", "open_orders": 2,
        }
        self.raise_on_quote = None
        self.raise_on_order = None
        self.raise_on_orders_mine = None

    def get_json(self, path, *, session_cookie=None):
        self.calls.append(("GET", path, None, session_cookie, None))
        if path == "/services":
            return {"services": _SERVICES}
        if path == "/kb/articles":
            return {"articles": _KB}
        if path == "/sitemap":
            return {"destinations": _SITEMAP}
        if path == "/orders/mine":
            if self.raise_on_orders_mine:
                raise self.raise_on_orders_mine
            return self.orders_mine_response
        if path == "/customers/me":
            return self.customers_me_response
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
        if path == "/tickets":
            return self.ticket_response
        raise AssertionError(f"unexpected POST {path}")


@pytest.fixture
def backend(monkeypatch):
    """Turn the backend on, wired to a fake client; isolate the catalog cache."""
    from django.conf import settings

    from agent import backend as backend_mod

    fake = FakeBackend()
    monkeypatch.setattr(settings, "URBANTRENDS_API_BASE", "http://test")
    monkeypatch.setattr(backend_mod, "get_client", lambda: fake)
    for mod in (catalog, kb, sitemap):
        mod._http_cache.clear()
    yield fake
    for mod in (catalog, kb, sitemap):
        mod._http_cache.clear()


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
    """A backend outage on placement is a failure → loop retries then escalates,
    filing the ticket with the backend (system of record), not locally."""
    backend.raise_on_order = BackendError("backend_unreachable")
    session = Session.objects.create()
    handle_message(session, "order a landing page")
    submit_order_form(session, {"pages": 1})

    result = handle_message(session, "confirm")

    assert result.escalated is True
    assert Order.objects.count() == 0
    assert any(c[1] == "/tickets" for c in backend.calls)
    assert result.action["ticket_ref"] == "UT-1"
    assert Ticket.objects.count() == 0  # delegated to the backend, not stored locally


def test_kb_answer_sourced_from_backend(backend):
    session = Session.objects.create()
    result = handle_message(session, "what payment methods do you accept?")

    assert result.action["action"] == "kb_answer"
    assert result.action["topic"] == "payment_methods"
    assert result.reply == "We take M-Pesa or bank transfer once your order is confirmed."


def test_navigate_destination_sourced_from_backend(backend):
    session = Session.objects.create()
    result = handle_message(session, "where do I find your pricing?")

    assert result.action["action"] == "navigate"
    assert result.action["path"] == "/pricing"       # from the backend sitemap


def test_list_orders_from_backend(backend):
    session = Session.objects.create()
    session._ut_session_cookie = "cookie-xyz"
    result = handle_message(session, "show my orders")

    assert result.action["action"] == "orders"
    assert result.action["orders"][0]["ref"] == "UT-ORD-9"
    assert "UT-ORD-9" in result.reply
    mine = [c for c in backend.calls if c[1] == "/orders/mine"][0]
    assert mine[3] == "cookie-xyz"   # forwarded X-UT-Session


def test_list_orders_requires_sign_in(backend):
    backend.raise_on_orders_mine = BackendError("not_authenticated", status=401)
    session = Session.objects.create()
    result = handle_message(session, "show my orders")

    assert result.action["action"] == "navigate"
    assert result.action["path"] == "/login"


def test_check_login_enriched_from_customers_me(backend):
    session = Session.objects.create(customer_ref="amina@example.com")
    session._ut_session_cookie = "cookie-xyz"
    result = handle_message(session, "am I signed in?")

    assert result.action["signed_in"] is True
    assert result.action["open_orders"] == 2
    assert "Amina W." in result.reply


def test_ticket_delegated_to_backend(backend):
    session = Session.objects.create()
    session.customer_ref = "amina@example.com"
    session.save()
    session._ut_session_cookie = "cookie-xyz"
    handle_message(session, "my site keeps crashing")
    result = handle_message(session, "I want to speak to a human")

    assert result.action["action"] == "ticket_created"
    assert result.action["ticket_ref"] == "UT-1"
    assert result.escalated is True
    assert Ticket.objects.count() == 0  # backend is the system of record
    post = [c for c in backend.calls if c[1] == "/tickets"][0]
    _, _, body, cookie, idem = post
    assert body["category"] == "other" and body["reason"] == "agent_handoff"
    assert body["customer_ref"] == "amina@example.com"
    assert [m["text"] for m in body["transcript"]]      # server-authored transcript attached
    assert cookie == "cookie-xyz" and idem
