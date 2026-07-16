#!/usr/bin/env python3
"""Daily planner: gather context → build a plan with Claude → wake you with it.

Run it once each morning (see README for the cron line). Useful flags:
  --dry-run   gather + build the plan and print it, but send nothing
  -v          verbose logging
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from config import config
from notifiers import send_email, send_whatsapp
from planner import build_plan
from sources import (
    create_events,
    gather_calendar,
    gather_local,
    gather_news,
    gather_tasks,
    gather_urbantrends,
    gather_weather,
)

log = logging.getLogger("daily-planner")


def _read_profile(path: str) -> str:
    """Personal 'about me' context, if present, to tailor the briefing."""
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("profile unreadable: %s", exc)
        return ""


def gather_context() -> list[str]:
    """Collect every source; each returns "" when unconfigured/unavailable."""
    log.info("gathering context…")
    blocks = [
        gather_weather(config.city, config.timezone),
        gather_calendar(config.timezone),
        gather_urbantrends(config.urbantrends_api_url, config.urbantrends_api_token),
        gather_tasks(config.tasks_file, config.tasks_db),
        gather_local(
            config.local_paths,
            config.local_repos,
            config.local_max_file_bytes,
            config.local_recent_days,
        ),
        gather_news(config.news_feeds, config.news_max_items),
    ]
    present = [b for b in blocks if b.strip()]
    log.info("gathered %d/%d sources", len(present), len(blocks))
    return present


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build but do not send")
    parser.add_argument("--schedule", action="store_true",
                        help="write the planned time blocks to Google Calendar")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not config.anthropic_api_key:
        log.error("ANTHROPIC_API_KEY is not set — cannot build the plan.")
        return 1

    context = gather_context()

    log.info("asking Claude (%s) to build the plan…", config.claude_model)
    plan = build_plan(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
        user_name=config.user_name,
        context_blocks=context,
        profile=_read_profile(config.profile_file),
        timezone=config.timezone,
    )

    print("\n" + "=" * 70)
    print(f"SUBJECT: {plan.subject}\n")
    print("── WhatsApp ──")
    print(plan.whatsapp_message)
    print("\n── Email ──")
    print(plan.email_body)
    if plan.events:
        print("\n── Calendar events ──")
        for e in plan.events:
            loc = f"  @ {e.location}" if e.location else ""
            print(f"  {e.start[11:16]}–{e.end[11:16]}  {e.title}{loc}")
    print("=" * 70 + "\n")

    if args.dry_run or config.dry_run:
        log.info("dry-run: nothing sent, no events created.")
        return 0

    if args.schedule or config.schedule_events:
        if plan.events:
            created, skipped, failed = create_events(plan.events, config.timezone)
            log.info("calendar: %d created, %d already present, %d failed",
                     len(created), len(skipped), len(failed))
            if failed:
                log.error("could not create: %s", ", ".join(failed))
        else:
            log.info("scheduling on, but Claude proposed no events.")
    else:
        log.info("scheduling off — pass --schedule or set SCHEDULE_EVENTS=true to add events.")

    if config.email_enabled:
        try:
            send_email(
                api_key=config.resend_api,
                sender=config.email_from,
                to=config.email_to,
                subject=plan.subject,
                body_markdown=plan.email_body,
            )
        except Exception as exc:  # noqa: BLE001 — one channel failing shouldn't kill the other
            log.error("email failed: %s", exc)
    else:
        log.info("email not configured — skipping.")

    if config.whatsapp_enabled:
        try:
            send_whatsapp(
                phone=config.whatsapp_phone,
                apikey=config.callmebot_apikey,
                message=plan.whatsapp_message,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("whatsapp failed: %s", exc)
    else:
        log.info("whatsapp not configured — skipping.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
