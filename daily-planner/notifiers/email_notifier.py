"""Send the plan by email via the Resend HTTP API."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.resend.com/emails"


def send_email(
    *,
    api_key: str,
    sender: str,
    to: str,
    subject: str,
    body_markdown: str,
) -> None:
    # A minimal HTML part so the markdown is preserved with line breaks.
    html = "<pre style=\"font-family:inherit;white-space:pre-wrap\">" + (
        body_markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ) + "</pre>"

    resp = requests.post(
        _ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": sender,
            "to": [to],
            "subject": subject,
            "text": body_markdown,  # plain-text fallback (markdown renders fine)
            "html": html,
        },
        timeout=30,
    )
    resp.raise_for_status()
    log.info("email sent to %s (resend id: %s)", to, resp.json().get("id", "?"))
