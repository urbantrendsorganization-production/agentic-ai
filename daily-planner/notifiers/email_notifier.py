"""Send the plan by email over SMTP (SSL)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def send_email(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    to: str,
    subject: str,
    body_markdown: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    # Plain-text part is the markdown itself (renders fine and is universally safe).
    msg.set_content(body_markdown)
    # A minimal HTML part so the markdown is preserved with line breaks.
    html = "<pre style=\"font-family:inherit;white-space:pre-wrap\">" + (
        body_markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ) + "</pre>"
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    log.info("email sent to %s", to)
