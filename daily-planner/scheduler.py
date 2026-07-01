#!/usr/bin/env python3
"""Docker-native scheduler: run the planner once a day at RUN_AT (local time).

The container's TZ decides "local" — set TZ=Africa/Nairobi in compose. Output
goes to stdout so `docker compose logs planner-scheduler` shows each run.
Replaces the host systemd timer when running in Docker.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s scheduler: %(message)s",
)
log = logging.getLogger(__name__)


def _seconds_until(hh: int, mm: int) -> float:
    now = dt.datetime.now()
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=1)
    return (nxt - now).total_seconds()


def main() -> int:
    run_at = os.getenv("RUN_AT", "06:00")
    hh, mm = (int(x) for x in run_at.split(":"))
    log.info("scheduler up — daily run at %s (%s)",
             run_at, dt.datetime.now().astimezone().tzname())
    while True:
        wait = _seconds_until(hh, mm)
        log.info("next run in %.0f min", wait / 60)
        time.sleep(wait)
        log.info("running planner…")
        result = subprocess.run([sys.executable, "main.py"])
        log.info("planner exited with code %d", result.returncode)
        time.sleep(60)  # step past the trigger minute so we don't double-fire


if __name__ == "__main__":
    raise SystemExit(main())
