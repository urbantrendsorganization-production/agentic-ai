"""Account / login-status tool (proposal §5 — customer login).

Mika doesn't log anyone in — the host site (urbantrends.dev, headless allauth)
owns authentication. Identity is resolved once, server-side, when the session is
created (see agent/identity.py) and stored on `Session.customer_ref`. This tool
just lets Mika *report* whether the visitor is signed in and, if not, deep-link
them to the site's sign-in page (passkey or email code — handled entirely by the
site). She never collects a password, passkey, or code herself.
"""
from __future__ import annotations

from typing import Any

from .. import sitemap
from .base import Tool, ToolResult, register


@register
class CheckLoginTool(Tool):
    name = "check_login"
    description = (
        "Check whether the customer is already signed in on urbantrends.dev. Use "
        "when they ask about their account or want to sign in, or before an action "
        "that needs a signed-in user. Sign-in happens on the site with a passkey or "
        "an email code — never collect credentials yourself."
    )
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        if session.customer_ref:
            return ToolResult(
                ok=True,
                data={"signed_in": True, "customer_ref": session.customer_ref},
                summary=f"You're signed in as {session.customer_ref} — how can I help?",
            )
        dest = sitemap.resolve("signin")
        return ToolResult(
            ok=True,
            # Anonymous → hand the widget a navigate action to the site sign-in page.
            data={
                "signed_in": False,
                "action": "navigate",
                "path": dest.path,
                "label": dest.label,
            },
            summary=(
                "You're not signed in yet. I'll point you to the sign-in page — use "
                "your passkey or an email code, then pop back and we'll carry on."
            ),
        )
