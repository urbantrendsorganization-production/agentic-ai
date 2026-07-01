# Daily Planner — your morning wake-up agent

Each morning this gathers what's going on — your **UrbanTrends** open work, your
**Google Calendar**, a local **todo file**, the **weather**, and a short **news
brief** — asks **Claude** to turn it into a realistic, time-blocked plan for the
day, then **wakes you** with it over **email** and **WhatsApp**.

"Wake me up" here = a notification at a set time (driven by cron). Your phone's
email/WhatsApp notification is the alarm. The program itself runs on any
always-on machine (your laptop on a schedule, a Raspberry Pi, a small VPS).

```
sources ─┐
weather  │
calendar ├──► planner.py (Claude) ──► email  📧
tasks    │                       └──► WhatsApp 💬
news     │
UrbanTrends ┘
```

## What you need

Everything is optional except an Anthropic API key. Any source you don't
configure is simply skipped, so you can start minimal and add pieces later.

| Piece | How to enable | Required? |
|------|----------------|-----------|
| The plan itself | `ANTHROPIC_API_KEY` | **Yes** |
| Email delivery | SMTP (Gmail App Password works) | optional |
| WhatsApp delivery | CallMeBot free API key | optional |
| Weather | just set `CITY` (Open-Meteo, no key) | optional |
| News brief | RSS feed URLs (defaults provided) | optional |
| Personal todos | a `tasks.md` file | optional |
| UrbanTrends work | a JSON API URL (+ token) | optional |
| Calendar | Google OAuth client | optional |

## Setup

```bash
cd daily-planner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in what you have
cp tasks.example.md tasks.md   # optional: your personal todo list
```

### Email (Gmail example)
Create an **App Password** at <https://myaccount.google.com/apppasswords> (needs
2-step verification on) and put it in `SMTP_PASSWORD`. Host/port are already set
for Gmail in `.env.example`.

### WhatsApp (CallMeBot, free)
1. Add **+34 644 75 95 78** to your WhatsApp contacts.
2. Send it: `I allow callmebot to send me messages`.
3. It replies with your personal API key → put it in `CALLMEBOT_APIKEY`, and your
   number (with country code) in `WHATSAPP_PHONE`.

### UrbanTrends
Point `URBANTRENDS_API_URL` at any endpoint that returns JSON — a top-level
array, or `{"results": [...]}` / `{"tasks": [...]}`. Each item is read loosely
from common fields (`title`/`name`, `due`/`deadline`, `priority`, `status`), so
a standard Django REST list endpoint works without extra wiring. Add a bearer
token via `URBANTRENDS_API_TOKEN` if the endpoint is authenticated.

### Google Calendar (optional)
1. In the [Google Cloud console](https://console.cloud.google.com/) create an
   OAuth **Desktop app** client and enable the **Google Calendar API**.
2. Download the client JSON as `google_credentials.json` into this folder.
3. The first run opens a browser to authorise once and caches
   `google_token.json` for future runs.
If neither file is present, the calendar source is just skipped.

## Run it

```bash
# Build the plan and print it, send nothing — great for testing:
python main.py --dry-run

# Real run (sends email + WhatsApp for whatever you've configured):
python main.py
```

## Wake up on a schedule (cron)

Edit your crontab (`crontab -e`) and add — adjust the time and paths:

```cron
# 06:30 every day. Use absolute paths; cron has a bare environment.
30 6 * * *  cd /home/eduh/Developer/Sandbox/agentic-ai/daily-planner && /home/eduh/Developer/Sandbox/agentic-ai/daily-planner/.venv/bin/python main.py >> planner.log 2>&1
```

Times are in the machine's local timezone. For a laptop that may be asleep at
06:30, run it on an always-on box, or pair cron with `systemd` timers /
`anacron` so a missed run fires on wake.

## Files

```
main.py                 orchestrator + CLI
config.py               loads settings from .env
planner.py              calls Claude, returns a structured DailyPlan
sources/                weather, calendar, tasks, urbantrends, news (each degrades gracefully)
notifiers/              email (SMTP) + whatsapp (CallMeBot)
.env.example            copy to .env and fill in
tasks.example.md        copy to tasks.md for a personal todo list
```

## Notes

- Each source catches its own errors and returns a short "unavailable" note
  instead of crashing the run — a flaky feed never blocks your morning plan.
- The plan is generated with **`claude-opus-4-8`** (override via `CLAUDE_MODEL`)
  using structured output, so email and WhatsApp text come back cleanly
  separated.
- Secrets and the personal `tasks.md` are git-ignored.
