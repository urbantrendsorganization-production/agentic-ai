"""Central configuration, loaded from environment (.env supported)."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _password_hash() -> str:
    """Werkzeug hashes contain '$', which Docker Compose interpolates in
    env_file values — so we store the hash base64-encoded and decode here.
    Falls back to a plain APP_PASSWORD_HASH for values without '$'.
    """
    b64 = os.getenv("APP_PASSWORD_HASH_B64", "")
    if b64:
        try:
            return base64.b64decode(b64).decode()
        except Exception:
            return ""
    return os.getenv("APP_PASSWORD_HASH", "")


@dataclass
class Config:
    # Identity / locale
    user_name: str = os.getenv("USER_NAME", "there")
    city: str = os.getenv("CITY", "")
    timezone: str = os.getenv("TIMEZONE", "UTC")

    # Claude
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Email (Resend HTTP API)
    resend_api: str = os.getenv("RESEND_API", "")
    email_from: str = os.getenv("EMAIL_FROM", "onboarding@resend.dev")
    email_to: str = os.getenv("EMAIL_TO", "")

    # WhatsApp (CallMeBot)
    whatsapp_phone: str = os.getenv("WHATSAPP_PHONE", "")
    callmebot_apikey: str = os.getenv("CALLMEBOT_APIKEY", "")

    # UrbanTrends
    urbantrends_api_url: str = os.getenv("URBANTRENDS_API_URL", "")
    urbantrends_api_token: str = os.getenv("URBANTRENDS_API_TOKEN", "")

    # Local tasks
    tasks_file: str = os.getenv("TASKS_FILE", "tasks.md")
    tasks_db: str = os.getenv("TASKS_DB", "tasks.db")

    # Personal profile ("about me") to tailor the briefing
    profile_file: str = os.getenv("PROFILE_FILE", "profile.md")

    # Web UI auth
    secret_key: str = os.getenv("SECRET_KEY", "")
    app_user: str = os.getenv("APP_USER", "edwin")
    app_password_hash: str = field(default_factory=_password_hash)
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    # News
    news_feeds: list[str] = field(
        default_factory=lambda: _split(os.getenv("NEWS_FEEDS"))
        or [
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
        ]
    )
    news_max_items: int = int(os.getenv("NEWS_MAX_ITEMS", "6"))

    # Behaviour flags (set by CLI)
    dry_run: bool = False

    @property
    def email_enabled(self) -> bool:
        return all([self.resend_api, self.email_from, self.email_to])

    @property
    def whatsapp_enabled(self) -> bool:
        return all([self.whatsapp_phone, self.callmebot_apikey])


config = Config()
