"""Pytest + Django wiring.

Tests force the keyless StubPlanner (settings.ANTHROPIC_API_KEY = "") so the P1
gate is proven with zero network calls and zero cost.
"""
import django
from django.conf import settings


def pytest_configure():
    settings.ANTHROPIC_API_KEY = ""
    django.setup()
