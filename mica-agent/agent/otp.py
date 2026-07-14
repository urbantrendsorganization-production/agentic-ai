"""OTP delivery, behind one interface with swappable backends.

Same pattern as the planner: a keyless `console` backend runs the whole login
flow locally and in tests, while the real Africa's Talking SMS stack (primary +
fallback, per proposal §5) drops in later selected by OTP_BACKEND — no change to
the tools or loop.
"""
from __future__ import annotations

import logging
import secrets

from django.conf import settings

log = logging.getLogger(__name__)


def generate_code() -> str:
    """A 6-digit numeric OTP (zero-padded)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def mask(destination: str) -> str:
    """Redact a destination for user-facing text: e***@x.com / +2547***5678."""
    if "@" in destination:
        local, _, domain = destination.partition("@")
        head = local[0] if local else ""
        return f"{head}***@{domain}"
    if len(destination) <= 4:
        return "***"
    return f"{destination[:4]}***{destination[-2:]}"


class OtpSender:
    def send(self, *, channel: str, destination: str, code: str) -> bool:
        raise NotImplementedError


# Dev/test seam: the console backend records what it "sent" so tests (and a
# human running locally) can read the code. Never used by a real backend.
CONSOLE_OUTBOX: list[dict] = []


class ConsoleOtpSender(OtpSender):
    """Logs the code instead of sending it. Zero cost, no external provider."""

    def send(self, *, channel: str, destination: str, code: str) -> bool:
        CONSOLE_OUTBOX.append({"channel": channel, "destination": destination, "code": code})
        log.info("OTP for %s via %s: %s", mask(destination), channel, code)
        return True


_SENDERS = {
    "console": ConsoleOtpSender,
    # "africastalking": AfricasTalkingOtpSender,  # drops in during hardening
}


def get_sender() -> OtpSender:
    backend = getattr(settings, "OTP_BACKEND", "console")
    sender_cls = _SENDERS.get(backend, ConsoleOtpSender)
    return sender_cls()
