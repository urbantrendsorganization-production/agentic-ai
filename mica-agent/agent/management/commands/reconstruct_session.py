"""Replay a session from its append-only AgentEvent log (proposal §10, P6).

Success metric §10: *any session is fully reconstructable from AgentEvent alone.*
This command is the audit-review tool that proves it — it prints the exact loop
timeline for a session and checks the log's integrity (gapless, monotonic seqs).

    ./.venv/bin/python manage.py reconstruct_session <session-id>
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from agent.models import Session


class Command(BaseCommand):
    help = "Reconstruct and audit a session's timeline from its AgentEvent log."

    def add_arguments(self, parser):
        parser.add_argument("session_id")

    def handle(self, *args, **opts):
        try:
            session = Session.objects.get(id=opts["session_id"])
        except Exception as exc:  # bad UUID or missing row → clean CLI error, not a trace
            raise CommandError(f"no such session: {opts['session_id']} ({exc})")

        events = list(session.events.order_by("seq"))
        who = session.customer_ref or "(anonymous)"
        self.stdout.write(f"Session {session.id}  ·  customer_ref={who}  ·  {len(events)} events")

        for e in events:
            self.stdout.write(f"  [{e.seq:>3}] {e.step:<8} {e.payload}")

        # Integrity: seqs must be gapless and monotonic (1..N), no dupes.
        seqs = [e.seq for e in events]
        gapless = seqs == list(range(1, len(seqs) + 1))
        respond = sum(1 for e in events if e.step == "respond")
        self.stdout.write(
            f"integrity: gapless={gapless}  responds={respond}  "
            f"seq_range={seqs[0] if seqs else 0}..{seqs[-1] if seqs else 0}"
        )
        if not gapless:
            raise CommandError("AUDIT FAILURE: event sequence has gaps or duplicates")
