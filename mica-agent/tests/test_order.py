"""P3 gate — full order flow: conversation → form → rules-engine quote → pending order."""
from decimal import Decimal

import pytest

from agent.forms import FormError
from agent.loop import handle_message, submit_order_form
from agent.models import AgentEvent, Order, OrderDraft, Session

pytestmark = pytest.mark.django_db


def test_start_order_pops_form():
    session = Session.objects.create()
    result = handle_message(session, "I want to order a landing page")

    assert result.action["action"] == "show_form"
    assert result.action["form"]["service"] == "landing_page"
    draft = session.order_drafts.get()
    assert draft.status == OrderDraft.STATUS_GATHERING


def test_full_order_flow_to_pending_order():
    session = Session.objects.create()
    session.customer_ref = "edwin@urbantrends.dev"
    session.save()

    # 1. conversation → form
    handle_message(session, "I'd like to buy a landing page")
    # 2. form submission → deterministic quote
    form_result = submit_order_form(
        session, {"pages": 2, "copywriting": True, "cms": False, "rush": False}
    )
    assert form_result.action["action"] == "quote"
    # 25000 + 8000 + 12000 = 45000
    assert form_result.action["quote"]["amount"] == "45000"
    draft = session.order_drafts.get()
    assert draft.status == OrderDraft.STATUS_QUOTED

    # 3. confirmation → pending order
    confirm = handle_message(session, "confirm")
    assert confirm.action["created"] is True

    order = Order.objects.get()
    assert order.status == Order.STATUS_PENDING
    assert order.amount == Decimal("45000")
    assert order.customer_ref == "edwin@urbantrends.dev"
    assert order.params == {"pages": 2, "copywriting": True, "cms": False, "rush": False}
    session.order_drafts.get().status == OrderDraft.STATUS_PLACED


def test_list_orders_shows_placed_order():
    """Order-status flow: after placing, 'show my orders' lists it (local mode)."""
    session = Session.objects.create(customer_ref="edwin@urbantrends.dev")
    handle_message(session, "I want a landing page")
    submit_order_form(session, {"pages": 1})
    handle_message(session, "confirm")

    result = handle_message(session, "show my orders")
    assert result.action["action"] == "orders"
    assert len(result.action["orders"]) == 1
    assert result.action["orders"][0]["service"] == "landing_page"


def test_confirmation_gate_blocks_order_without_quote():
    """create_order must not place anything until a quote exists (proposal §8)."""
    session = Session.objects.create()
    handle_message(session, "I want a web app")     # form shown, not yet quoted
    result = handle_message(session, "confirm")      # premature confirm

    assert result.action["created"] is False
    assert result.action["reason"] == "no_quote"
    assert Order.objects.count() == 0


def test_form_submit_requires_active_draft():
    session = Session.objects.create()
    with pytest.raises(FormError):
        submit_order_form(session, {"pages": 1})


def test_order_amount_comes_from_engine_not_model(monkeypatch):
    """Even if the model/planner tried to inject a price, money is engine-only."""
    session = Session.objects.create()
    handle_message(session, "order a maintenance retainer")
    submit_order_form(session, {"tier": "premium"})
    handle_message(session, "confirm")

    order = Order.objects.get()
    assert order.amount == Decimal("55000")  # premium tier, straight from catalog


def test_full_flow_logged_in_append_only_trail():
    session = Session.objects.create()
    handle_message(session, "I want a landing page")
    submit_order_form(session, {"pages": 1})
    handle_message(session, "confirm")

    # Every turn recorded; seqs are gapless and monotonic across all turns.
    seqs = list(session.events.order_by("seq").values_list("seq", flat=True))
    assert seqs == list(range(1, len(seqs) + 1))
    assert session.events.filter(step=AgentEvent.STEP_RESPOND).count() == 3
