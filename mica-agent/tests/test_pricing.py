"""P3 — the deterministic pricing rules engine (proposal §8)."""
from decimal import Decimal

import pytest

from agent import pricing
from agent.forms import FormError, validate_submission


def test_landing_base_price():
    q = pricing.quote("landing_page", {"pages": 1, "copywriting": False, "cms": False, "rush": False})
    assert q.currency == "KES"
    assert q.amount == Decimal("25000")


def test_landing_full_stack_with_rush_surcharge():
    params = {"pages": 3, "copywriting": True, "cms": True, "rush": True}
    q = pricing.quote("landing_page", params)
    # 25000 + 2*8000 + 12000 + 15000 = 68000; +25% rush = 17000 → 85000
    assert q.amount == Decimal("85000")
    labels = [i["label"] for i in q.breakdown]
    assert "Rush delivery (25%)" in labels


def test_pricing_is_deterministic():
    params = {"auth": True, "integrations": 2, "timeline_weeks": 3}
    a = pricing.quote("web_app", params)
    b = pricing.quote("web_app", params)
    assert a.as_dict() == b.as_dict()
    # 120000 + 30000 + 2*15000 = 180000; timeline<4 → +20% (36000) = 216000
    assert a.amount == Decimal("216000")


def test_maintenance_tiers():
    assert pricing.quote("maintenance", {"tier": "basic"}).amount == Decimal("15000")
    assert pricing.quote("maintenance", {"tier": "premium"}).amount == Decimal("55000")


def test_unknown_service_raises():
    with pytest.raises(KeyError):
        pricing.quote("spaceship", {})


# ── form validation ──────────────────────────────────────────────────────────

def test_form_applies_defaults():
    cleaned = validate_submission("landing_page", {"pages": 2})
    assert cleaned == {"pages": 2, "copywriting": False, "cms": False, "rush": False}


def test_form_coerces_types():
    cleaned = validate_submission(
        "landing_page", {"pages": "4", "copywriting": "true", "cms": 0, "rush": False}
    )
    assert cleaned["pages"] == 4 and cleaned["copywriting"] is True and cleaned["cms"] is False


def test_form_rejects_out_of_range():
    with pytest.raises(FormError) as exc:
        validate_submission("landing_page", {"pages": 99})
    assert "pages" in exc.value.errors


def test_form_rejects_bad_enum():
    with pytest.raises(FormError) as exc:
        validate_submission("maintenance", {"tier": "platinum"})
    assert "tier" in exc.value.errors


def test_form_requires_required_without_default():
    # web_app.integrations has a default, but feed a bad type to force an error.
    with pytest.raises(FormError):
        validate_submission("web_app", {"integrations": "lots", "timeline_weeks": 8})
