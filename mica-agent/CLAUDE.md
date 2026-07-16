# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **agent service** for Mica — an agentic customer bot for urbantrends.dev
(Django + DRF orchestrator). `PROPOSAL.md` is the source of truth for scope,
guardrails, and the gate-driven phase plan (P1–P6). The embeddable widget now
lives in `widget/` (self-contained vanilla JS, shadow-DOM isolated) and is served
for dev by `runserver` at `/`.

**Current phase: P6 hardening (complete) + live backend integration.** P1–P5
done + P2 login reworked to host-auth. Tools: `echo` (P1); `check_login` /
`navigate` (P2); `start_order` / `create_order` / `list_orders` (P3);
`answer_question` / `create_ticket` (P4). Build on the existing `Tool` contract;
don't run ahead of the current gate.

**Backend integration (BACKEND_APIS.md / MICA_INTEGRATION.md).** Each data
source is a provider behind one interface, selected by env: when
`URBANTRENDS_API_BASE` is set, Mica sources catalog, pricing, orders, KB,
sitemap, tickets, and customer profile from the urbantrends.dev backend
(`agent/backend.py` — stdlib client, Bearer service key, `/api/v1/agent` prefix,
`X-UT-Session` forwarding for user-scoped calls, `Idempotency-Key`, typed
`BackendError`). Unset → the in-repo static modules (`catalog.py`, `pricing.py`,
`kb.py`, `sitemap.py`, `tickets.py`), which stay the keyless dev/test default.
Deterministic money still holds — the amount's *source* moves to the backend's
quote engine, but the model never sets it. Orders + tickets delegate fully
(backend = system of record; tickets fall back to a local row if it's
unreachable so an escalation is never lost).

P6: **rate limits** (`agent/ratelimit.py` — fixed-window per-IP/per-session
via the cache, fail-open; 429 + `Retry-After` on the session/message endpoints);
a **red-team suite** (`tests/test_guardrails.py` — injected prices ignored, money
stays engine-only, whitelists unescapable, a message can't set identity or place
an order); **audit review** (`manage.py reconstruct_session <id>` replays a
session from `AgentEvent` and checks the log is gapless — success metric §10);
and **cost tracking** — `ClaudePlanner` surfaces per-call token usage on
`Decision.usage` (`_usage_dict`, incl. cache tokens); the loop folds it across
retries and logs it on each `act` event plus a per-turn total on `respond`, also
exposed as `TurnResult.usage`. The stub reports no usage (keyless → no cost).

**Login is a host-site auth *check*, not an agent-run flow.** Mika is an embedded
helper on urbantrends.dev (headless django-allauth, passkey / email-code). She
never issues codes or keeps a user table. `agent/identity.py` verifies the
visitor's forwarded `sessionid` against allauth's headless session endpoint
(pluggable seam: keyless `StubIdentityProvider` for dev/tests via an
`X-UT-Identity` header, `AllauthIdentityProvider` for real). Identity is resolved
once at **session creation** → `Session.customer_ref`; anonymous otherwise.
`check_login` reports status and deep-links anonymous visitors to `/login`.

P5 widget (`widget/mika-widget.js`): renders the Mika design (cyan chrome / red
Mika) and consumes the loop's `action` outcomes (`show_form` → dynamic form,
`quote` → server quote card, `created` → confirmation, `navigate` → toast,
`ticket_created`/`escalated` → apologetic + ticket). Avatar state maps to the
loop step (§7). It posts with `credentials:"include"` so the host `sessionid`
reaches the agent through the site proxy. It never prices anything.

P4 support flow: `answer_question` serves *canned* KB content — the model picks a
whitelisted topic key (`agent/kb.py`), never writes the answer. `create_ticket`
is the escalation path: the model proposes only a subject/category and the loop
attaches a **server-authored transcript snapshot** (`agent/tickets.py`) to a
`Ticket`. The loop also auto-opens a ticket when it exhausts retries
(`reason=verify_exhausted`), so every escalation leaves a durable, audited
artifact. A tool signals a human handoff via `result.data["escalated"]`, which
the loop lifts onto `TurnResult.escalated`.

P3 ordering flow (a small state machine over `OrderDraft`, one active per
session): `start_order` names a catalog service and pops its dynamic form →
widget POSTs to `/order/form/` → `loop.submit_order_form` validates
(`agent/forms.py`) + prices (`agent/pricing.py`) deterministically, stores the
quote on the draft (status `quoted`) → `create_order` is **gated on a quoted
draft** and copies the server-computed amount into a `pending` `Order`.
- **Deterministic money is the load-bearing rule**: prices come only from
  `agent/pricing.py` + `agent/catalog.py`. Order tools never accept or emit a
  price; `create_order` takes no args. Never let the model or a form field set an
  amount.
- `TurnResult.action` carries the verified tool's structured result to the widget
  (`action: show_form|navigate|quote`, or an outcome like `{created: true}`).
- Form submission is deliberately NOT routed through the planner — structured
  input needs validation + the engine, not an LLM — but it's still logged as a
  full turn so the audit trail stays unbroken.

Key patterns to reuse:
- **Business outcome vs failure.** A tool can return `ok=True` yet report a
  negative result in `data` (e.g. `check_login` → `signed_in=False`, or a
  premature confirm → `created=False`). That is a *verified run* and must NOT
  retry/escalate. Reserve `ok=False` for real failures (provider down).
  `Tool.verify()` owns the intent check.
- **Pluggable providers behind one interface**, selected by env, with a keyless
  dev/test default — see `agent/planner.py` (`get_planner`) and
  `agent/identity.py` (`get_identity_provider`, `IDENTITY_BACKEND`;
  `StubIdentityProvider` is the dev/test seam).
- **Whitelists over free text.** `navigate` and `check_login` can only reach
  `agent/sitemap.py` destinations; `answer_question` only serves `agent/kb.py`
  topics. The model proposes; the server validates.

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
./.venv/bin/python manage.py reconstruct_session <id>  # audit: replay a session (P6)
```

The widget demo is served at `/` by `runserver`; the embeddable is
`widget/mika-widget.js`.

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
