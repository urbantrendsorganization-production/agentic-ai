"""Customer login via OTP (proposal §5).

Two tools, because login spans two user turns:

* `request_login_code` — the visitor gives an email/phone; we mint a one-time
  code, store it hashed, and hand it to the OTP sender. A send failure is a real
  tool failure (`ok=False`) so the loop retries/escalates (mirrors the SMS
  primary→fallback intent). Requesting a code is idempotent per session: any
  earlier unconsumed challenge is invalidated first.
* `verify_login_code` — the visitor gives the code. Whether or not it matches,
  the tool *ran* correctly, so `ok=True`; the match/miss is a business outcome
  in `result.data['verified']`. Only a real match binds Session.customer_ref.

Guardrail: the model never sees or handles the code hash; it only passes the
raw destination/code, which we re-validate server-side.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from ..models import LoginChallenge, Session
from ..otp import generate_code, get_sender, mask
from .base import Tool, ToolResult, register

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


@register
class RequestLoginCodeTool(Tool):
    name = "request_login_code"
    description = (
        "Start login for a customer by sending a one-time verification code to "
        "their email or phone. Call this when the user wants to log in / sign in "
        "and has given an email address or phone number."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "enum": ["email", "phone"],
                "description": "Whether the code is sent to an email or a phone number.",
            },
            "destination": {
                "type": "string",
                "description": "The email address or phone number to send the code to.",
            },
        },
        "required": ["channel", "destination"],
    }

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        channel = args.get("channel")
        destination = (args.get("destination") or "").strip()
        if channel not in {"email", "phone"}:
            raise ValueError("channel must be 'email' or 'phone'")
        if channel == "email" and not _EMAIL_RE.match(destination):
            raise ValueError("destination is not a valid email address")
        if channel == "phone" and not _PHONE_RE.match(destination):
            raise ValueError("destination is not a valid phone number")
        return {"channel": channel, "destination": destination}

    def run(self, args: dict[str, Any], *, session: Session) -> ToolResult:
        # One live challenge per session: retire any earlier unconsumed ones.
        session.challenges.filter(consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )

        code = generate_code()
        LoginChallenge.objects.create(
            session=session,
            channel=args["channel"],
            destination=args["destination"],
            code_hash=make_password(code),
            max_attempts=settings.OTP_MAX_ATTEMPTS,
            expires_at=timezone.now() + dt.timedelta(seconds=settings.OTP_TTL_SECONDS),
        )

        sent = get_sender().send(
            channel=args["channel"], destination=args["destination"], code=code
        )
        if not sent:
            return ToolResult(ok=False, data={}, error="send_failed")

        return ToolResult(
            ok=True,
            data={"channel": args["channel"], "destination": args["destination"]},
            summary=(
                f"I've sent a 6-digit code to {mask(args['destination'])}. "
                "Pop it in here and I'll get you signed in."
            ),
        )


@register
class VerifyLoginCodeTool(Tool):
    name = "verify_login_code"
    description = (
        "Verify the one-time login code the customer received. Call this once the "
        "user provides the 6-digit code after request_login_code."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The 6-digit code the customer entered.",
            }
        },
        "required": ["code"],
    }

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        code = re.sub(r"\s+", "", str(args.get("code", "")))
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("code must be 6 digits")
        return {"code": code}

    def run(self, args: dict[str, Any], *, session: Session) -> ToolResult:
        challenge = session.challenges.order_by("-created_at").first()
        if challenge is None or not challenge.is_active():
            return ToolResult(
                ok=True,
                data={"verified": False, "reason": "no_active_code"},
                summary=(
                    "That code has expired or there isn't one pending. "
                    "Want me to send a fresh code?"
                ),
            )

        challenge.attempts += 1
        if check_password(args["code"], challenge.code_hash):
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["attempts", "consumed_at"])
            session.customer_ref = challenge.destination
            session.save(update_fields=["customer_ref"])
            return ToolResult(
                ok=True,
                data={"verified": True, "customer_ref": challenge.destination},
                summary="You're signed in — welcome back! What would you like to do?",
            )

        challenge.save(update_fields=["attempts"])
        left = max(challenge.max_attempts - challenge.attempts, 0)
        if left == 0:
            return ToolResult(
                ok=True,
                data={"verified": False, "reason": "too_many_attempts"},
                summary=(
                    "That code didn't match and we've hit the attempt limit. "
                    "I can send a brand-new code whenever you're ready."
                ),
            )
        return ToolResult(
            ok=True,
            data={"verified": False, "reason": "mismatch", "attempts_left": left},
            summary=f"That code didn't match — {left} attempt(s) left. Try again?",
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        # The tool did its job as long as it ran; a wrong code is a valid
        # outcome to report, not a failure to retry/escalate.
        return bool(result.ok)
