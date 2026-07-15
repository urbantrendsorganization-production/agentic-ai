"""Django settings for the Mica agent service.

Local dev runs on SQLite with no external services; the Docker/production stack
supplies DATABASE_URL (Postgres) and REDIS_URL through the environment. Every
knob is read from `.env` so nothing secret lives in the repo.
"""
from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
DEBUG = _bool("DEBUG", "true")
ALLOWED_HOSTS = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# SQLite by default; DATABASE_URL (Postgres) in Docker/production.
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

# ── Celery / Redis ──────────────────────────────────────────────────────────
# Wired here so P2+ can offload tool calls without a config change. Until a
# broker is running, tasks are called synchronously (CELERY_TASK_ALWAYS_EAGER).
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = _bool("CELERY_TASK_ALWAYS_EAGER", "true")

# ── Agent / Claude ──────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_ROUTER_MODEL = os.getenv("CLAUDE_ROUTER_MODEL", "claude-haiku-4-5-20251001")
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "4"))

# ── Host-site identity (login) ────────────────────────────────────────────────
# Mika is an embedded helper agent: she verifies the visitor's urbantrends.dev
# login rather than authenticating anyone herself (agent/identity.py). "stub" is
# the keyless dev/test default; "allauth" introspects the host site's headless
# allauth session endpoint at ALLAUTH_BASE_URL.
IDENTITY_BACKEND = os.getenv("IDENTITY_BACKEND", "stub")
ALLAUTH_BASE_URL = os.getenv("ALLAUTH_BASE_URL", "").strip()

# ── Rate limits (proposal §8, P6) ─────────────────────────────────────────────
# Fixed-window per-minute caps, enforced via the cache (LocMemCache in dev,
# Redis in prod). Fail-open by design (see agent/ratelimit.py).
RATE_LIMIT_ENABLED = _bool("RATE_LIMIT_ENABLED", "true")
RATE_LIMIT_IP_SESSIONS_PER_MINUTE = int(os.getenv("RATE_LIMIT_IP_SESSIONS_PER_MINUTE", "30"))
RATE_LIMIT_IP_MESSAGES_PER_MINUTE = int(os.getenv("RATE_LIMIT_IP_MESSAGES_PER_MINUTE", "60"))
RATE_LIMIT_SESSION_MESSAGES_PER_MINUTE = int(
    os.getenv("RATE_LIMIT_SESSION_MESSAGES_PER_MINUTE", "30")
)

STATIC_URL = "static/"
# The embeddable Mika widget (P5) is served from here in dev so `runserver` can
# host the full demo end-to-end; production ships it as a static asset/CDN embed.
STATICFILES_DIRS = [BASE_DIR / "widget"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Surface the agent's own logs (incl. the console OTP backend in dev) on stderr.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "agent": {"handlers": ["console"], "level": os.getenv("AGENT_LOG_LEVEL", "INFO")},
    },
}
