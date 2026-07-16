# Mica ↔ UrbanTrends backend API handout

**Audience:** the urbantrends.dev backend team.
**Purpose:** the APIs urbantrends.dev must expose so **Mica** (the agent service
in this repo) sources her data from the live business backend instead of the
static tables she ships with today.

Mica already treats every one of these data sources as a **pluggable provider
behind one interface**, selected by env, with a keyless static default for
dev/tests (the same seam as `get_planner()` / `get_identity_provider()`). So
"wiring the backend" means: for each domain below, add an *HTTP-backed provider*
that calls your endpoint; the in-repo static module stays as the dev/test stub.
No loop or tool code changes — only the data source moves.

> **The one guardrail that must not bend: deterministic money.** Prices and
> order amounts come from a server-side rules engine, never from the model.
> Today that engine is `agent/pricing.py`. Moving it to your backend is fine —
> **the number's *source* moves, but it stays server-authoritative and the model
> still never sets it.** The quote endpoint (§3) is therefore the load-bearing
> one: Mica sends validated requirements, your backend returns the money.

---

## Who is Mica?

**Mica** is UrbanTrends' agentic customer assistant — an AI helper embedded on
urbantrends.dev as a chat widget (the on-screen persona is **Mika**, the cyan/red
character in the corner bubble). Unlike a scripted FAQ bot, Mica **takes real
actions** on the visitor's behalf: she checks whether they're signed in, deep-links
them around the site, walks them through ordering a service (collecting
requirements in a dynamic form, showing a real quote, placing a pending order),
answers common support questions, and escalates to a human by opening a ticket
when she can't resolve something.

She is a **separate service** (this repo — Django/DRF) that sits alongside your
site, not code inside it. The visitor's browser talks to your site; your site's
proxy forwards chat messages (and the visitor's `sessionid`) to Mica. Mica does
the reasoning and calls back into **your backend** — the APIs in this document —
to get real business data and perform real actions. **UrbanTrends remains the
system of record for everything real** (identity, prices, orders, tickets); Mica
orchestrates, but she owns none of it.

**How she works, in one paragraph** (this is *why* the contract below is shaped
the way it is): every visitor message runs through a **wait → act → verify →
respond** loop. In *act*, a Claude model is handed a fixed, whitelisted set of
**tools** and proposes *one* — a tool name plus arguments (e.g. "`start_order`,
service=`landing_page`"). It **cannot free-type an action, a URL, a price, or an
answer.** The loop then validates those arguments server-side, calls the matching
capability (increasingly, *your* API), and **verifies** the result achieved the
intent before replying — retrying, then escalating to a human ticket if not.
Every step is written to an **append-only audit log**, so any conversation is
fully reconstructable after the fact.

That design gives your backend three guarantees worth relying on as you build
these endpoints:

- **The model never touches your systems directly.** It only proposes; Mica's
  loop validates and calls you. Your endpoints only ever see server-checked input.
- **Closed sets, not free text.** Which services exist, which support answers are
  allowed, where she may navigate — all are whitelists *your APIs define* and the
  model merely *selects from*. It can't invent an option you didn't return.
- **Deterministic money.** The model gathers requirements; **your backend computes
  the price.** No request from Mica ever carries a model-chosen amount, and Mika
  never shows a price your backend didn't return.

The rest of this document is the list of endpoints that let Mica source that real
data and perform those real actions against your backend.

---

## 0. Conventions (apply to every endpoint)

| Concern | Contract |
|---|---|
| **Base URL** | One env var on Mica: `URBANTRENDS_API_BASE` (e.g. `https://urbantrends.dev`). Agent-facing endpoints live under `…/api/v1/agent/`. |
| **Versioning** | Path-versioned (`/api/v1/…`). Additive changes only within a version; breaking changes bump to `/v2/`. |
| **Service auth** | Every call carries a service credential Mica→backend: `Authorization: Bearer <URBANTRENDS_API_KEY>` (or mTLS). This authenticates *the agent service*, not the visitor. |
| **User-scoped calls** | Calls that read/write a specific customer's data (orders, "my orders", quote-for-user) **also** forward the visitor's host session: header `X-UT-Session: <sessionid>`. The backend resolves the user from it (never trust a `customer_ref` in the body for authorization). Calls marked *app-scoped* below need only the service credential. |
| **Content type** | `application/json` in and out; UTF-8. |
| **Money** | Currency `KES`. Amounts are **strings of whole shillings** (`"25000"`), never floats — matches `Quote.as_dict()` / `Order.amount`. Every priced response includes an itemised `breakdown: [{label, amount}]`. |
| **Errors** | Non-2xx returns `{"error": {"code": "<machine_code>", "message": "<human>", "fields": {"<field>": "<why>"}}}`. `fields` is present for validation errors (422). |
| **Idempotency** | State-changing POSTs (orders, tickets) accept `Idempotency-Key: <uuid>`; a repeat with the same key returns the original result, never a duplicate. |
| **Latency / failure** | Mica calls with a short timeout (~4 s) and **degrades safely** rather than 500-ing (anonymous identity, "I couldn't reach the catalog just now", escalate to a ticket). Endpoints should be fast and fail closed on money, open on read-only lookups. |
| **Caching** | Catalog, KB, and sitemap are cacheable — send `ETag`/`Cache-Control`; Mica will honour it. Quotes and orders are **never** cached. |

---

## 1. Identity — *is this visitor signed in?*

Mica does not authenticate anyone; she reuses the host session. This is **already
built** against allauth headless (`agent/identity.py` → `AllauthIdentityProvider`).
Documented here as the contract Mica depends on.

### `GET /_allauth/browser/v1/auth/session`  *(existing allauth headless)*
- **Auth:** forwarded visitor `sessionid` cookie.
- **Purpose:** resolve the signed-in customer once, at Mica session creation →
  stored on `Session.customer_ref`.
- **200 (signed in):**
  ```json
  { "meta": { "is_authenticated": true },
    "data": { "user": { "id": 42, "email": "amina@example.com",
                        "username": "amina", "display": "Amina W." } } }
  ```
- **401 (anonymous):** treated as "not signed in" — Mika deep-links to `/login`.

Mica reads only `meta.is_authenticated` and `data.user.{email|username|id|display}`.
Keep those keys stable.

**Optional enrichment — `GET /api/v1/agent/customers/me`** *(user-scoped)*: a
richer profile (name, open-order count, tier) if you want Mika to greet by name
or answer "how many orders do I have". Not required for launch.

---

## 2. Catalog — *what UrbanTrends sells + the form to quote it*

Replaces `agent/catalog.py` (services, aliases, **dynamic form schemas**). This is
the source of truth for (a) which services exist and (b) what requirements to
collect. Mika renders the returned form schema verbatim.

### `GET /api/v1/agent/services`  *(app-scoped, cacheable)*
- **Purpose:** the full sellable catalog + each service's requirement form.
- **200:**
  ```json
  {
    "services": [
      {
        "key": "landing_page",
        "label": "Landing page",
        "description": "A marketing site / landing page.",
        "aliases": ["landing page", "landing", "website", "marketing site"],
        "form": {
          "service": "landing_page",
          "title": "Landing page — project brief",
          "fields": [
            { "name": "pages", "type": "integer", "label": "Number of pages",
              "required": true, "min": 1, "max": 8, "default": 1 },
            { "name": "copywriting", "type": "boolean",
              "label": "Need copywriting?", "default": false },
            { "name": "cms", "type": "boolean",
              "label": "CMS / editable content?", "default": false },
            { "name": "rush", "type": "boolean",
              "label": "Rush (2-week) delivery?", "default": false }
          ]
        }
      }
    ]
  }
  ```
- **Field schema** (must match what `agent/forms.py` validates): `type ∈
  {integer, boolean, enum, string}`; optional `min`, `max` (integer), `options`
  (enum), `required`, `default`. `aliases` is optional (only the keyless stub
  planner uses them; real Claude gets the keys as a tool enum).

### `GET /api/v1/agent/services/{key}`  *(optional, single service)*
Same object as one array element. Convenient but not required.

---

## 3. Pricing / quote — **deterministic money (highest priority)**

Replaces the pricing authority in `agent/pricing.py` + the `price` rules in
`agent/catalog.py`. Mika collects requirements via the form, **re-validates them**,
then asks your backend for the authoritative price. The model is never on this path.

### `POST /api/v1/agent/services/{key}/quote`  *(app-scoped; user-scoped if pricing is customer-specific)*
- **Purpose:** compute the definitive quote for a service + validated params.
- **Request:**
  ```json
  { "params": { "pages": 3, "copywriting": true, "cms": false, "rush": false } }
  ```
- **200:**
  ```json
  {
    "quote_id": "q_8f21c4",
    "currency": "KES",
    "amount": "53000",
    "breakdown": [
      { "label": "Base landing page", "amount": "25000" },
      { "label": "Extra pages ×2", "amount": "16000" },
      { "label": "Copywriting", "amount": "12000" }
    ],
    "expires_at": "2026-07-16T12:00:00Z"
  }
  ```
- **422 (bad params):** `{"error":{"code":"invalid_params","message":"...","fields":{"pages":"must be at most 8"}}}`.
- **Contract notes:**
  - **The backend recomputes and validates** — never trust the params blindly;
    Mika validates too, but yours is the authority.
  - Return a **`quote_id`** Mika can later hand to the order endpoint (§4) so the
    order amount is looked up server-side, not re-sent. If you don't want quote
    ids, the order endpoint must recompute from `service + params` instead.
  - `amount` must equal the sum of `breakdown` amounts (Mika/audit may assert this).
  - Response shape mirrors `Quote.as_dict()` — keep `currency`, `amount`,
    `breakdown[{label, amount}]`.

---

## 4. Orders — *place a pending order; check status*

Today Mika writes a local `Order` (`agent/tools/order.py`). Recommended target:
**your backend is the system of record**; Mika POSTs the order to you and keeps
only the returned reference in her audit log.

### `POST /api/v1/agent/orders`  *(user-scoped)*
- **Purpose:** create a **pending** order after the customer confirms a quote.
  Mirrors the current confirmation gate (`create_order` only fires on a quoted draft).
- **Request:**
  ```json
  { "quote_id": "q_8f21c4", "session_ref": "<mica-session-uuid>" }
  ```
  *(or, if no quote ids: `{ "service": "landing_page", "params": {…} }` — the
  backend then recomputes the price. **Never** accept an `amount` in the body.)*
- **Headers:** `X-UT-Session`, `Idempotency-Key`.
- **201:**
  ```json
  { "order_id": "ord_10293", "ref": "UT-ORD-10293", "status": "pending",
    "currency": "KES", "amount": "53000",
    "breakdown": [ … ], "created_at": "2026-07-16T11:02:00Z" }
  ```
- **Guardrail:** the amount is derived server-side from `quote_id` (or recomputed
  from params) — **the request never carries money.** This is the same rule as
  today's `create_order` taking no price arg.
- **409 / expired quote:** `{"error":{"code":"quote_expired"}}` → Mika re-quotes.

### `GET /api/v1/agent/orders/mine`  *(user-scoped)*
- **Purpose:** back the "show my orders" / order-status flow (KB `order_status`,
  sitemap `orders`).
- **200:** `{ "orders": [ { "ref": "UT-ORD-10293", "service": "landing_page",
  "status": "pending", "amount": "53000", "currency": "KES",
  "created_at": "…" } ] }`

### `GET /api/v1/agent/orders/{ref}`  *(user-scoped)* — single order for read-back. Optional.

---

## 5. Knowledge base — *canned support answers*

Replaces `agent/kb.py`. Preserve the **whitelist model**: Mika's `answer_question`
tool only serves reviewed content; the model selects a topic key, never writes the
answer. So the backend owns the answer text; Mika never composes it.

### `GET /api/v1/agent/kb/articles`  *(app-scoped, cacheable)*
- **200:**
  ```json
  {
    "articles": [
      { "key": "payment_methods", "title": "Payment methods",
        "answer": "We take payment via M-Pesa or bank transfer once your order is confirmed…",
        "aliases": ["payment", "how do i pay", "mpesa", "bank transfer"],
        "tags": ["billing"] }
    ]
  }
  ```
- `key` becomes the enum the model chooses from; `answer` is served verbatim.
  `aliases`/`tags` optional (stub-planner routing / grouping).
- Editing answers in your CMS updates Mika with no deploy (respect `ETag`).

*(If you later want semantic retrieval instead of a fixed list, expose
`GET /api/v1/agent/kb/search?q=…` returning ranked **topic keys** — keep it
returning whitelisted keys, not free-text answers, so the guardrail holds.)*

---

## 6. Sitemap — *where Mika may deep-link*

Replaces `agent/sitemap.py`. A whitelist so `navigate` can never send a visitor to
an arbitrary/hostile URL. Keep it in sync with your real route table.

### `GET /api/v1/agent/sitemap`  *(app-scoped, cacheable)*
- **200:**
  ```json
  {
    "destinations": [
      { "key": "pricing", "path": "/pricing", "label": "Pricing",
        "aliases": ["pricing", "prices", "cost", "plans"] },
      { "key": "orders", "path": "/account/orders", "label": "Your orders",
        "aliases": ["my orders", "order history"] },
      { "key": "signin", "path": "/login", "label": "Sign in",
        "aliases": ["sign in", "log in", "my account"] }
    ]
  }
  ```
- Paths are **site-relative**; the widget resolves them against the current origin
  and navigates client-side. `signin` and `orders` keys should exist (Mika uses
  them for the login deep-link and order-status).

---

## 7. Support tickets — *escalate to a human*

Today Mika writes a local `Ticket` with a server-authored transcript
(`agent/tickets.py`). Recommended target: **file into your real support/helpdesk
system** so a human actually sees it. Mika keeps proposing only subject/category
and attaches the transcript; the model never writes the transcript.

### `POST /api/v1/agent/tickets`  *(user-scoped if signed in; app-scoped otherwise)*
- **Purpose:** open a support ticket carrying the full conversation. Fired on
  agent hand-off (`create_ticket`) **and** automatically on retry-exhaustion
  (`reason=verify_exhausted`).
- **Request:**
  ```json
  {
    "subject": "Refund on order UT-ORD-10293",
    "category": "billing",
    "reason": "agent_handoff",
    "customer_ref": "amina@example.com",
    "session_ref": "<mica-session-uuid>",
    "transcript": [
      { "role": "user", "text": "I need a refund", "at": "2026-07-16T10:59:00Z" },
      { "role": "agent", "text": "I've opened a ticket…", "at": "2026-07-16T10:59:03Z" }
    ]
  }
  ```
  - `category ∈ {order, billing, technical, general, other}`;
    `reason ∈ {agent_handoff, verify_exhausted}` (matches `Ticket` model).
  - `transcript` is **server-authored by Mica** from her Message log — treat it as
    trusted evidence, not user input.
- **Headers:** `Idempotency-Key` (so a retried escalation doesn't double-file).
- **201:** `{ "ticket_id": "tkt_5567", "ref": "UT-5567", "status": "open" }`
  — Mika reads `ref` back to the customer.

### `GET /api/v1/agent/tickets/{ref}`  *(user-scoped)* — status read-back. Optional.

---

## Mapping: Mica source → backend endpoint

| Mica module / tool | Today (static, in-repo) | Backend endpoint to build | Priority |
|---|---|---|---|
| `agent/identity.py` | allauth headless *(already wired)* | `GET /_allauth/browser/v1/auth/session` | ✅ done |
| `agent/catalog.py` (services + forms) | `SERVICES` dict | `GET /api/v1/agent/services` | **P0** |
| `agent/pricing.py` + catalog `price` rules | in-code Decimal rules | `POST /api/v1/agent/services/{key}/quote` | **P0** |
| `create_order` / `Order` | local DB write | `POST /api/v1/agent/orders` | P1 |
| order-status / "my orders" | *(none yet)* | `GET /api/v1/agent/orders/mine` | P1 |
| `agent/kb.py` (`answer_question`) | `ARTICLES` dict | `GET /api/v1/agent/kb/articles` | P2 |
| `agent/sitemap.py` (`navigate`) | `DESTINATIONS` dict | `GET /api/v1/agent/sitemap` | P2 |
| `create_ticket` / `Ticket` | local DB write | `POST /api/v1/agent/tickets` | P2 |

**Suggested sequencing.** **P0** (services + quote) is what turns Mika's money
real and unblocks everything downstream — do these first. **P1** makes orders and
their status live in your system of record. **P2** moves the read-only whitelists
(KB, sitemap) and support tickets. Identity is already integrated.

---

## What stays the same on Mica's side (so you can rely on it)

- **The model never touches your DB.** It proposes a tool name + args; Mica's loop
  validates, calls your API, and verifies the result. Your endpoints see only
  server-validated input.
- **Whitelists hold.** Services, KB topics, and sitemap destinations remain
  closed sets the model *selects from* — your APIs define the set; the model can't
  add to it.
- **Deterministic money holds.** Amounts flow catalog/quote → order; no request
  from Mica to you ever carries a model-chosen price, and Mika never renders a
  price your backend didn't return.
- **Audit trail holds.** Every backend call is still logged as a loop step in the
  append-only `AgentEvent` log; a session stays fully reconstructable.
- **Dev/test keep working keyless.** The in-repo static modules become the stub
  provider (`URBANTRENDS_API_BASE` unset → static data), so the test suite and
  local demo run with no backend, exactly as now.

---

## Open questions for the backend team

1. **Quote ids vs recompute:** do you want to issue `quote_id`s (Mika stores it,
   order references it) or have the order endpoint recompute from `service+params`?
   Either preserves the guardrail; pick one and we align.
2. **Customer-specific pricing:** are quotes ever per-customer (discounts, tiers)?
   If so, the quote endpoint becomes user-scoped (forward `X-UT-Session`).
3. **Service auth mechanism:** shared bearer key, signed JWT, or mTLS between Mica
   and the backend?
4. **Ticket destination:** which helpdesk/system should `POST /tickets` land in,
   and what categories does it recognise (so we map cleanly to
   `{order,billing,technical,general,other}`)?
5. **Session forwarding:** confirm the proxy forwards the visitor `sessionid` to
   Mica, and that Mika may forward it onward to you as `X-UT-Session` for
   user-scoped calls.
