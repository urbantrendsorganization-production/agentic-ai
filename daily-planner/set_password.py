#!/usr/bin/env python3
"""Set the task-UI login password.

Prompts for a password (hidden), hashes it, and writes APP_PASSWORD_HASH into
.env. The plaintext password is never stored or printed.

Usage:  .venv/bin/python set_password.py
Then:   systemctl --user restart daily-planner-ui.service
"""
from __future__ import annotations

import base64
from getpass import getpass
from pathlib import Path

from werkzeug.security import generate_password_hash

ENV = Path(__file__).with_name(".env")
KEY = "APP_PASSWORD_HASH_B64"


def main() -> int:
    pw = getpass("New password: ")
    if len(pw) < 8:
        print("Please use at least 8 characters.")
        return 1
    if pw != getpass("Confirm password: "):
        print("Passwords don't match.")
        return 1

    # Base64 so the '$' in the hash isn't interpolated by Docker Compose.
    hashed = base64.b64encode(generate_password_hash(pw).encode()).decode()
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    out, found = [], False
    for line in lines:
        if line.startswith(f"{KEY}="):
            out.append(f"{KEY}={hashed}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{KEY}={hashed}")
    ENV.write_text("\n".join(out) + "\n")

    print("\n✓ Password set in .env.")
    print("  Apply it:  docker compose up -d --force-recreate planner-ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
