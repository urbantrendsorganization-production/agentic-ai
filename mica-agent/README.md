# Mica — UrbanTrends Agentic Customer Bot

Agentic customer-facing bot for urbantrends.dev. It doesn't just answer — it
**acts**: log a customer in, navigate the site, place an order, pop dynamic
forms, and resolve issues. See [`PROPOSAL.md`](PROPOSAL.md) for the full vision,
guardrails, and phase plan.

This repo is the **agent service** (Django + DRF orchestrator). The Next.js
widget is a separate deliverable; through P4 the agent is driven by a plain
placeholder widget and the test suite.

## The agent loop

Every user message runs a strict four-step loop (`agent/loop.py`):

1. **Wait** — a message arrives; it's recorded.
2. **Act** — the planner (`agent/planner.py`) picks a whitelisted tool via Claude
   tool use, or replies directly.
3. **Verify** — the tool runs and its result is checked against the intent;
   retry, then escalate on failure. *This* is what makes it agentic.
4. **Respond & log** — reply to the user and append an `AgentEvent`.

The `AgentEvent` table is **append-only**: any session is fully reconstructable
from the log alone.

## Status — P2 (login + navigation) ✅

- **P1** — loop skeleton working end-to-end with the `echo` tool.
- **P2** — OTP login (`request_login_code` / `verify_login_code`, pluggable
  sender) and deep-link `navigate` off a read-only site map. Next: P3 (ordering
  + dynamic forms). Remaining capabilities land on the same `Tool` contract.

### OTP login

Login spans two turns: the visitor gives an email/phone → a 6-digit code is
minted (stored hashed) and handed to the OTP sender → the visitor returns the
code → a match binds `Session.customer_ref`. A wrong code is reported as a
retryable prompt, not an escalation; a genuine *send* failure escalates. The
sender is pluggable (`OTP_BACKEND`): `console` for dev/tests (logs the code),
Africa's Talking SMS in production.

### Navigation

`agent/sitemap.py` is a whitelist of destinations → site-relative paths. The
`navigate` tool can only resolve to a listed destination (never an arbitrary
URL) and returns `{action, path, label}` for the widget to execute client-side.

## Quick start (local, no external services)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # runs on SQLite; no key needed yet
python manage.py migrate
python manage.py runserver
```

Try it:

```bash
SID=$(curl -sX POST localhost:8000/api/sessions/ | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sX POST localhost:8000/api/sessions/$SID/messages/ \
  -H 'content-type: application/json' -d '{"text":"hi mika"}'
```

### Turning on real Claude

Leave `ANTHROPIC_API_KEY` blank and the loop uses a deterministic **stub
planner** (zero cost, always routes to `echo`) — this is what the tests and the
P1 gate run on. Set the key in `.env` and the loop switches to real Claude tool
use automatically, no code change.

## Tests & lint

```bash
pytest          # proves the P1 gate: wait → act → verify → respond → log
ruff check .
```

## Production shape

`docker compose up` brings up web (gunicorn) + Postgres + Redis + a Celery
worker. Set `DATABASE_URL`, `REDIS_URL`, and `ANTHROPIC_API_KEY` via `.env`.
Deploy target: Docker Compose on Hetzner, Caddy-proxied, bound to 127.0.0.1.
