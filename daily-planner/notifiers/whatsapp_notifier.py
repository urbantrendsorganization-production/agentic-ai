"""Send a WhatsApp message via the free CallMeBot API.

Setup (one time): add +34 644 75 95 78 to your WhatsApp contacts and send it
"I allow callmebot to send me messages". It replies with your personal API key.
https://www.callmebot.com/blog/free-api-whatsapp-messages/
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

ENDPOINT = "https://api.callmebot.com/whatsapp.php"
# CallMeBot truncates very long messages; keep well under its limit.
MAX_LEN = 900


def send_whatsapp(*, phone: str, apikey: str, message: str) -> None:
    text = message if len(message) <= MAX_LEN else message[: MAX_LEN - 1] + "…"
    resp = requests.get(
        ENDPOINT,
        params={"phone": phone, "text": text, "apikey": apikey},
        timeout=30,
    )
    # CallMeBot returns 200 with an HTML body; surface non-2xx loudly.
    resp.raise_for_status()
    log.info("whatsapp message sent to %s", phone)
