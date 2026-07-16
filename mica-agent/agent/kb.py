"""Support knowledge base for common questions (proposal §5 — issue resolution).

A whitelist, like catalog.py and sitemap.py: the `answer_question` tool can only
return answers that live here, so the model serves *canned, reviewed* content —
it never invents support answers (guardrail §8: user content is data, whitelists
over free text). `aliases` let the keyless stub planner map a free-text question
onto an article; real Claude picks the topic key directly via tool use.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Article:
    key: str
    title: str
    answer: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


ARTICLES: dict[str, Article] = {
    a.key: a
    for a in [
        Article(
            "how_ordering_works",
            "How ordering works",
            "Tell me what you'd like built and I'll pop a short form to capture the "
            "details, then work out an exact quote. Nothing is charged upfront — a "
            "confirmed order simply goes to our team as pending, and they follow up "
            "to finalise everything.",
            ("how do i order", "how does ordering", "how to order", "place an order",
             "ordering work"),
        ),
        Article(
            "payment_methods",
            "Payment methods",
            "We take payment via M-Pesa or bank transfer once your order is confirmed "
            "and the team has been in touch. Orders start pending — you're never "
            "charged automatically through the chat.",
            ("payment", "how do i pay", "mpesa", "m-pesa", "bank transfer", "methods do you accept"),
        ),
        Article(
            "timelines",
            "Typical timelines",
            "As a rough guide: a landing page runs about 1–2 weeks, a custom web app "
            "about 4–8 weeks depending on scope, and maintenance is ongoing monthly. "
            "Need it sooner? We offer rush delivery on some services for a surcharge.",
            ("timeline", "timelines", "turnaround", "delivery time", "how fast"),
        ),
        Article(
            "revisions",
            "Revisions",
            "Every project includes revision rounds so we can get the details right — "
            "we'll agree the specifics when the team scopes your order.",
            ("revision", "revisions", "amendments", "feedback rounds"),
        ),
        Article(
            "services_offered",
            "What we build",
            "UrbanTrends builds landing pages, custom web applications, and offers "
            "monthly maintenance retainers. Tell me which you're after and I can quote "
            "it for you right here.",
            ("what do you offer", "what do you build", "what services", "what can you do"),
        ),
        Article(
            "order_status",
            "Checking your order",
            "Once you're signed in you can see your orders under your account. Say "
            "'show my orders' and I'll take you straight there.",
            ("order status", "check my order", "where is my order", "track order"),
        ),
    ]
}


# ── Provider seam (BACKEND_APIS.md) ──────────────────────────────────────────
# Answers come from the static ARTICLES above (keyless dev/test default) or the
# live backend (GET /kb/articles) when URBANTRENDS_API_BASE is set. Either way the
# model only ever picks a whitelisted key; the answer text is served, never written.


def _match(articles: dict[str, Article], text: str) -> Article | None:
    lowered = text.lower()
    best: tuple[int, Article] | None = None
    for article in articles.values():
        for alias in article.aliases:
            if alias in lowered and (best is None or len(alias) > best[0]):
                best = (len(alias), article)
    return best[1] if best else None


class _StaticKb:
    def all(self) -> dict[str, Article]:
        return ARTICLES


def _article_from_json(a: dict) -> Article:
    return Article(
        key=a["key"],
        title=a.get("title", a["key"]),
        answer=a.get("answer", ""),
        aliases=tuple(a.get("aliases", ())),
    )


class _HttpKb:
    _TTL = 300.0  # seconds; KB content is edited rarely

    def __init__(self, client) -> None:
        self._client = client
        self._cache: dict[str, Article] | None = None
        self._at = 0.0

    def all(self) -> dict[str, Article]:
        import time

        now = time.monotonic()
        if self._cache is not None and now - self._at < self._TTL:
            return self._cache
        data = self._client.get_json("/kb/articles")
        self._cache = {a["key"]: _article_from_json(a) for a in data.get("articles", [])}
        self._at = now
        return self._cache


_STATIC = _StaticKb()
_http_cache: dict[str, _HttpKb] = {}


def _provider():
    from django.conf import settings

    base = getattr(settings, "URBANTRENDS_API_BASE", "")
    if not base:
        return _STATIC
    prov = _http_cache.get(base)
    if prov is None:
        from .backend import get_client

        prov = _HttpKb(get_client())
        _http_cache[base] = prov
    return prov


def get(key: str) -> Article:
    article = _provider().all().get(key)
    if article is None:
        raise KeyError(f"unknown article: {key!r}")
    return article


def keys() -> list[str]:
    return list(_provider().all())


def match_text(text: str) -> Article | None:
    """Best-effort free text → article for the keyless stub planner only.

    Prefers the longest alias hit so specific phrases win over generic ones.
    """
    return _match(_provider().all(), text)
