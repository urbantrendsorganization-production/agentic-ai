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


def get(key: str) -> Article:
    article = ARTICLES.get(key)
    if article is None:
        raise KeyError(f"unknown article: {key!r}")
    return article


def keys() -> list[str]:
    return list(ARTICLES)


def match_text(text: str) -> Article | None:
    """Best-effort free text → article for the keyless stub planner only.

    Prefers the longest alias hit so specific phrases win over generic ones.
    """
    lowered = text.lower()
    best: tuple[int, Article] | None = None
    for article in ARTICLES.values():
        for alias in article.aliases:
            if alias in lowered and (best is None or len(alias) > best[0]):
                best = (len(alias), article)
    return best[1] if best else None
