"""Per-session / per-IP rate limiting (proposal §8 — rate limits).

Backed by Django's cache framework: a fixed-window counter keyed by
(bucket, key, window-slot). Dev/tests use the default in-memory cache; production
points CACHES at Redis — the same store the rest of the stack uses. **Fails
open**: a cache hiccup must never become a 500 or lock legitimate users out.
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache


def client_ip(request) -> str:
    """Best-effort client IP, honouring the proxy's X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def allow(bucket: str, key: str, *, limit: int, window: int = 60) -> tuple[bool, int]:
    """Fixed-window counter. Returns (allowed, retry_after_seconds).

    `retry_after` is meaningful only when blocked. Disabled (or a non-positive
    limit) always allows.
    """
    if not getattr(settings, "RATE_LIMIT_ENABLED", True) or limit <= 0:
        return True, 0

    now = int(time.time())
    slot = now // window
    ck = f"rl:{bucket}:{key}:{slot}"
    try:
        if cache.add(ck, 1, timeout=window):
            count = 1
        else:
            count = cache.incr(ck)
    except Exception:  # cache unavailable → fail open, never block on infra
        return True, 0

    if count > limit:
        return False, window - (now % window)
    return True, 0
