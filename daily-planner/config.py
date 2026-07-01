"""Central configuration, loaded from environment (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@dataclass
class Config:
    # Identity / locale
    user_name: str = os.getenv("USER_NAME", "there")
    city: str = os.getenv("CITY", "")
    timezone: str = os.getenv("TIMEZONE", "UTC")

    # Claude
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

    # Email
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "465"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    email_to: str = os.getenv("EMAIL_TO", "")

    # WhatsApp (CallMeBot)
    whatsapp_phone: str = os.getenv("WHATSAPP_PHONE", "")
    callmebot_apikey: str = os.getenv("CALLMEBOT_APIKEY", "")

    # UrbanTrends
    urbantrends_api_url: str = os.getenv("URBANTRENDS_API_URL", "")
    urbantrends_api_token: str = os.getenv("URBANTRENDS_API_TOKEN", "")

    # Local tasks
    tasks_file: str = os.getenv("TASKS_FILE", "tasks.md")

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
        return all([self.smtp_host, self.smtp_user, self.smtp_password, self.email_to])

    @property
    def whatsapp_enabled(self) -> bool:
        return all([self.whatsapp_phone, self.callmebot_apikey])


config = Config()
