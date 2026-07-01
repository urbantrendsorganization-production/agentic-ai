"""A short morning news brief from RSS feeds (via feedparser)."""
from __future__ import annotations

import logging

import feedparser

log = logging.getLogger(__name__)


def gather_news(feeds: list[str], max_items: int = 6) -> str:
    if not feeds:
        return ""
    headlines: list[str] = []
    try:
        # Spread the item budget across the configured feeds.
        per_feed = max(1, max_items // len(feeds))
        for url in feeds:
            parsed = feedparser.parse(url)
            source = parsed.feed.get("title", url)
            for entry in parsed.entries[:per_feed]:
                title = entry.get("title", "").strip()
                if title:
                    headlines.append(f"- [{source}] {title}")
        headlines = headlines[:max_items]
        if not headlines:
            return ""
        return "Top headlines:\n" + "\n".join(headlines)
    except Exception as exc:  # noqa: BLE001
        log.warning("news source failed: %s", exc)
        return f"News: unavailable ({exc})."
