"""Pytest + Django wiring.

Tests force the keyless StubPlanner (settings.ANTHROPIC_API_KEY = "") so the P1
gate is proven with zero network calls and zero cost.
"""
import django
import pytest
from django.conf import settings


def pytest_configure():
    settings.ANTHROPIC_API_KEY = ""
    # Keep the suite hermetic: no backend calls unless a test opts in.
    settings.URBANTRENDS_API_BASE = ""
    django.setup()


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    """Isolate the fixed-window rate limiter between tests (shared LocMemCache)."""
    from django.core.cache import cache

    cache.clear()
    yield
