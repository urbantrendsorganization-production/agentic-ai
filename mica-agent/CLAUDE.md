# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **agent service** for Mica — an agentic customer bot for urbantrends.dev
(Django + DRF orchestrator). `PROPOSAL.md` is the source of truth for scope,
guardrails, and the gate-driven phase plan (P1–P6). The Next.js embed widget is
a separate deliverable and not in this repo; through P4 the agent is exercised
via the test suite and a placeholder widget.

**Current phase: P2 done → P3 next.** Tools so far: `echo` (P1), plus
`request_login_code` / `verify_login_code` and `navigate` (P2). P3 is ordering +
dynamic forms (rules-engine quotes — deterministic money, never the model), then
P4 support/tickets. Build on the existing `Tool` contract; don't run ahead of
the current gate.

Key P2 patterns to reuse:
- **Business outcome vs failure.** A tool can return `ok=True` yet report a
  negative result in `data` (e.g. a wrong OTP → `verified=False`). That is a
  *verified run* and must NOT retry/escalate. Reserve `ok=False` for real
  failures (provider down). `Tool.verify()` owns the intent check.
- **Pluggable providers behind one interface**, selected by env, with a keyless
  dev/test default — see `agent/planner.py` (`get_planner`) and `agent/otp.py`
  (`get_sender`, `OTP_BACKEND`; `CONSOLE_OUTBOX` is the dev/test seam).
- **Whitelists over free text.** `navigate` can only reach `agent/sitemap.py`
  destinations; OTP inputs are regex-validated server-side. The model proposes;
  the server validates.

## Commands

All Python runs through the local venv (`./.venv/bin/python`); there is no
system Django.

```bash
./.venv/bin/pip install -r requirements-dev.txt   # runtime + test/lint tooling
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py runserver
./.venv/bin/python -m pytest                       # full suite (the P1 gate)
./.venv/bin/python -m pytest tests/test_loop.py::test_happy_path_runs_full_loop
./.venv/bin/ruff check .
./.venv/bin/python manage.py makemigrations agent  # after any models.py change
```

`docker compose up` runs the production shape (web + Postgres + Redis + Celery).

## Architecture — the agent loop

The whole system is one loop in `agent/loop.py::handle_message`, run inside a
single DB transaction per message (proposal §4). Understanding these pieces
together is the fast path to being productive:

- **`agent/loop.py`** — orchestrates wait → act → verify → respond & log. The
  **verify** step (`_verify`) is the point of the whole design: it checks a
  tool's result against the caller's intent, retries up to `AGENT_MAX_STEPS`,
  then **escalates**. A tool raising an exception is caught and treated as a
  verify failure, never a 500.
- **`agent/planner.py`** — the "act" brain, behind one interface with two impls.
  `get_planner()` returns `ClaudePlanner` (real Anthropic tool use) when
  `ANTHROPIC_API_KEY` is set, else `StubPlanner` (deterministic, keyless, always
  routes to `echo`). **Tests and the P1 gate run on the stub** — no network, no
  cost. Dropping the key into `.env` flips on real Claude with no code change.
- **`agent/tools/`** — the whitelist. `base.py` defines `Tool` (Claude-facing
  `input_schema` + server-side `validate` + side-effecting `run` returning a
  `ToolResult`) and the process-wide `registry`. Tools self-register via the
  `@register` decorator at import time (wired in `agent/apps.py::ready`). Add a
  new capability = new `Tool` subclass in `agent/tools/`, exported from
  `tools/__init__.py`.
- **`agent/models.py`** — `AgentEvent` is an **append-only** audit log (one row
  per loop step, monotonic `seq` unique per session); any session is fully
  reconstructable from it (success metric §10). Never update/delete events; the
  admin blocks both. `Session`/`Message` hold only lightweight state + the
  human-readable transcript.

## Non-negotiable guardrails (proposal §8)

When adding tools or touching the loop, preserve these — they are the point of
the project, not optional polish:

- **Model never touches the DB.** It only proposes a tool name + args; the loop
  validates and runs. Every tool re-validates its own input in `validate()`
  regardless of what the model sent.
- **Deterministic money.** Prices/quotes come from a rules engine, never the
  model (relevant from P3). The model gathers requirements only.
- **User content is data, not instructions.** Don't add free-text execution
  paths; the system prompt pins the tool contract.
- **State-changing actions need a confirmation gate** before execution (P3+).

## Conventions

- Config comes only from the environment via `.env` (`config/settings.py`).
  Local dev defaults to SQLite and the stub planner so everything runs with no
  external services and no key. `DATABASE_URL`/`REDIS_URL` switch to
  Postgres/Redis in Docker.
- Ruff `E,F,I` (line length 100, `E501` ignored); the loop/tools deliberately
  catch broad exceptions to degrade gracefully — that's intentional, not a lint
  miss to "fix".
- Models default to `claude-sonnet-4-6` (conversation) and
  `claude-haiku-4-5-20251001` (routing); override via `.env`.
- Matches the sibling `../daily-planner` toolchain (venv, ruff config, pytest,
  `anthropic` SDK, `.env` via python-dotenv).
