# UrbanTrends ↔ Mica integration guide

**Audience:** the Mica agent service repo.
**Purpose:** this is the *implemented* counterpart to `BACKEND_APIS.md`. The
UrbanTrends backend now exposes the full agent API under `/api/v1/agent/`. This
document tells Mica exactly how to point her pluggable providers at it — the
real paths, headers, payloads, status codes, and the behaviours to rely on.

> **Nothing about Mica's design changes.** Each domain below is still a provider
> behind one interface, selected by env, with the keyless static module as the
> dev/test default. "Wiring the backend" = for each domain, add an HTTP-backed
> provider that calls the endpoint here. No loop or tool code changes.

---

## 0. Setup (do this first)

### Env vars Mica needs

| Var | Value | Notes |
|---|---|---|
| `URBANTRENDS_API_BASE` | `https://urbantrends.dev` (prod) / `http://localhost:8000` (dev) | Agent endpoints live under `…/api/v1/agent/`. |
| `URBANTRENDS_API_KEY` | the shared service key | Sent as `Authorization: Bearer …` on **every** call. Ask backend team for the value; in local dev the backend runs keyless so any/no key works. |

When `URBANTRENDS_API_BASE` is unset, keep using the in-repo static modules
(`agent/catalog.py`, `agent/pricing.py`, …) exactly as today — that stays the
dev/test stub.

### Headers on every call

```
Authorization: Bearer <URBANTRENDS_API_KEY>      # authenticates the Mica service
Content-Type: application/json                    # on POSTs
```

### Extra header on user-scoped calls

Calls that read/write a specific customer's data (orders, quotes-for-user,
`customers/me`) **must** forward the visitor's host session:

```
X-UT-Session: <sessionid>                          # the visitor's Django sessionid
```

The backend resolves the user from that sessionid. **Never** send a customer id
in the body for authorization — it is ignored for auth. If the header is missing
or the session is anonymous, user-scoped calls return `401 not_authenticated`.

### Where the sessionid comes from (the widget → Mica handoff)

The visitor's `sessionid` is an **`HttpOnly` cookie**, so the browser widget
**cannot** read it via `document.cookie` — and it does not need to. `HttpOnly`
only blocks JavaScript *reads*; the browser still *sends* the cookie on requests.
Mica reads it **server-side** from the incoming `Cookie` header.

This works only because the widget talks to Mica **same-origin**. The widget is
served on `urbantrends.dev` and its API base is the relative path `/agent/api`,
which the site proxies (Caddy → Next.js `/agent/*` rewrite → the Mica service).
Because the call is same-origin, the browser attaches the `urbantrends.dev`
session cookie automatically (it is `SameSite=Lax; Path=/`, host-only), and both
proxy hops forward the `Cookie` header unchanged.

```
Browser (urbantrends.dev)
  │  widget fetch → /agent/api/*   (same-origin, credentials: "include")
  │  ⇒ browser auto-attaches the HttpOnly sessionid cookie
  ▼
Caddy :443 → Next.js :3000 → [/agent/* rewrite] → Mica service
  │  (both hops forward the Cookie header)
  ▼
Mica server  — parse `sessionid=…` from the request Cookie header
  │  ⇒ set  X-UT-Session: <sessionid>  on user-scoped UT backend calls
  ▼
UT backend   — resolves the user from the sessionid → 200
```

**What Mica must do:**

1. **Widget:** issue every `/agent/api/*` fetch with `credentials: "include"`
   (or `"same-origin"`). Keep the API base a **relative, same-origin path**
   (`/agent/api`) — a cross-origin absolute URL would make the request
   cross-site and `SameSite=Lax` would then withhold the cookie.
2. **Mica server:** read the `sessionid` value from the inbound `Cookie` header
   and forward it verbatim as `X-UT-Session` on user-scoped UT calls (orders,
   quotes-for-user, `customers/me`). No change is needed on the UT backend.

**Identity shortcut:** for "is the visitor signed in / greet by name", the widget
can call `GET /_allauth/browser/v1/auth/session` **directly from the browser**
(same-origin, cookie auto-sent) and read `meta.is_authenticated` +
`data.user.{id|email|display}` — no server round-trip and no sessionid handling.
Only **write / user-scoped** calls need the `X-UT-Session` path, because those
require the secret `Authorization: Bearer` key, which must never reach the
browser.

> **Security — the sessionid is a full-session credential.** Forwarding it lets
> Mica (and anything that logs its request headers) act as the *entire* user
> session, not just an agent scope. Therefore:
> - `MICA_AGENT_URL` (the `/agent/*` proxy target) **must be first-party /
>   self-hosted infra**, never a third-party SaaS host — otherwise the site
>   forwards `urbantrends.dev` session cookies to an external party.
> - Mica must **never log** the `Cookie` / `X-UT-Session` values and must reach
>   the UT backend over TLS.
> - If tighter scoping is wanted later, the UT backend can mint a short-lived,
>   agent-scoped token bound to the user for Mica to forward instead of the raw
>   sessionid. That is a future change; the contract above is satisfied by the
>   cookie-forwarding flow.

### Conventions

- **JSON** in and out, UTF-8.
- **Money** is `KES`, as **whole-shilling strings** (`"25000"`), never floats.
  Every priced response has `breakdown: [{label, amount}]` and
  `amount == sum(breakdown[].amount)`.
- **Errors** (any non-2xx): `{"error": {"code", "message", "fields"?}}`.
  `fields` (field → reason) is present on `422` validation errors.
- **Idempotency**: send `Idempotency-Key: <uuid>` on order/ticket POSTs; a repeat
  with the same key replays the original result, never duplicates.
- **Caching**: catalog, KB, and sitemap send `ETag` + `Cache-Control: max-age=300`.
  Send `If-None-Match` and honour `304`. Quotes and orders are never cached.
- **Timeouts**: call with a short timeout (~4 s) and **degrade safely** — do not
  surface a 500 to the visitor. Fail *closed* on money (no quote → don't invent
  one), *open* on read-only lookups (fall back to the static stub or a soft "I
  couldn't reach the catalog just now").

### Error codes you will see

| HTTP | `code` | Meaning / Mica's move |
|---|---|---|
| 403 | _(DRF default)_ | Bad/missing service key. Config error — fix `URBANTRENDS_API_KEY`. |
| 401 | `not_authenticated` | User-scoped call with no valid `X-UT-Session`. Deep-link to `/login`. |
| 404 | `not_found` | Unknown service/order/ticket/quote. |
| 422 | `invalid_params` | Form params failed validation; see `fields`. Re-collect. |
| 422 | `quote_unavailable` | Service has no deterministic price configured. Escalate/quote-request. |
| 409 | `quote_expired` | Quote TTL passed (default 24 h). Re-quote, then re-order. |

---

## 1. Identity — *is the visitor signed in?*

Already wired (`agent/identity.py` → `AllauthIdentityProvider`) against allauth
headless `GET /_allauth/browser/v1/auth/session`. No change. Read only
`meta.is_authenticated` and `data.user.{id|email|display}`.

**Optional enrichment (implemented):**

```
GET /api/v1/agent/customers/me            # user-scoped
→ 200 { "id": 42, "email": "amina@example.com",
        "display": "Amina W.", "open_orders": 2 }
```

Use for "greet by name" / "how many orders do I have". `401` if not signed in.

---

## 2. Catalog provider — services + requirement forms

Replaces `agent/catalog.py`.

```
GET /api/v1/agent/services                # app-scoped, cacheable
→ 200
{
  "services": [
    {
      "key": "landing_page",
      "label": "Landing page",
      "description": "A marketing site / landing page.",
      "aliases": ["landing page", "website"],
      "form": {
        "service": "landing_page",
        "title": "Landing page — project brief",
        "fields": [
          { "name": "pages", "type": "integer", "label": "Number of pages",
            "required": true, "min": 1, "max": 8, "default": 1 },
          { "name": "copywriting", "type": "boolean",
            "label": "Need copywriting?", "default": false }
        ]
      }
    }
  ]
}
```

- `key` is the service slug — hand these to the model as the tool enum.
- **Render `form` verbatim.** Field `type ∈ {integer, boolean, enum, string}`,
  with optional `min`/`max` (integer), `options` (enum — list of strings or
  `{value,label}`), `required`, `default`.
- `GET /api/v1/agent/services/{key}` returns one service (same object). `404`
  if unknown.
- Services with no admin form config still return a generic single-field brief
  form — always safe to render.

---

## 3. Pricing provider — deterministic quote (highest priority)

Replaces `agent/pricing.py`. **The model is never on this path.** Mika collects
+ re-validates params, then asks the backend for the authoritative number.

```
POST /api/v1/agent/services/landing_page/quote     # body = validated params
{ "params": { "pages": 3, "copywriting": true } }
→ 200
{
  "quote_id": "q_8f21c4a0",
  "currency": "KES",
  "amount": "53000",
  "breakdown": [
    { "label": "Base landing page", "amount": "25000" },
    { "label": "Extra pages ×2",    "amount": "16000" },
    { "label": "Copywriting",       "amount": "12000" }
  ],
  "expires_at": "2026-07-17T09:00:00Z"
}
```

**Store the `quote_id`.** Hand it to the order endpoint so the amount is looked
up server-side, never re-sent. The quote is valid until `expires_at` (default
24 h) — after that, ordering returns `409 quote_expired` and you re-quote.

- `422 invalid_params` + `fields` → params were rejected (Mika validates too, but
  the backend is the authority). Re-collect only the flagged fields.
- `422 quote_unavailable` → the service has no fixed price/rules; route to a
  human quote-request instead of guessing.
- Assert `amount == sum(breakdown)` in your audit step; the backend guarantees it.

---

## 4. Orders provider — place pending order / status

Recommended target from the spec: **the backend is the system of record.** Mika
keeps only the returned `ref` in her audit log.

```
POST /api/v1/agent/orders                 # user-scoped
Headers: X-UT-Session, Idempotency-Key
Body:    { "quote_id": "q_8f21c4a0" }     # preferred
     or  { "service": "landing_page", "params": { … } }   # backend recomputes
→ 201
{ "order_id": "ord_10293", "ref": "UT-ORD-10293", "service": "landing_page",
  "status": "pending", "currency": "KES", "amount": "53000",
  "breakdown": [ … ], "created_at": "2026-07-16T11:02:00Z" }
```

- **The body never carries money.** Amount is derived from `quote_id` (or
  recomputed from params). Sending an `amount` has no effect.
- Send an `Idempotency-Key` — a retried confirmation replays the same order.
- `409 quote_expired` → re-quote and retry. `401` → sign-in required first.

```
GET /api/v1/agent/orders/mine             # user-scoped
→ { "orders": [ { "order_id": "ord_10293", "ref": "UT-ORD-10293",
                  "service": "landing_page", "status": "pending",
                  "amount": "53000", "currency": "KES",
                  "created_at": "…" } ] }

GET /api/v1/agent/orders/UT-ORD-10293     # user-scoped, single (adds breakdown)
```

Order `status ∈ {pending, quoted, active, on_hold, completed, cancelled}`. The
`ref` (`UT-ORD-<n>`) is what you read back to the customer; `orders/{ref}` accepts
the full ref.

---

## 5. Knowledge-base provider — canned answers (whitelist)

Replaces `agent/kb.py`. The backend owns the answer text; the model only selects
a `key`, never composes the answer.

```
GET /api/v1/agent/kb/articles             # app-scoped, cacheable
→ { "articles": [
      { "key": "payment_methods", "title": "Payment methods",
        "answer": "We take payment via M-Pesa or bank transfer…",
        "aliases": ["payment", "mpesa", "bank transfer"], "tags": ["billing"] }
    ] }
```

- `key` → the enum the model chooses from; `answer` → served verbatim.
- Editing answers in the admin updates Mika with no deploy — respect the `ETag`.

---

## 6. Sitemap provider — deep-link whitelist

Replaces `agent/sitemap.py`. `navigate` may only target these.

```
GET /api/v1/agent/sitemap                 # app-scoped, cacheable
→ { "destinations": [
      { "key": "pricing", "path": "/pricing", "label": "Pricing",
        "aliases": ["pricing", "prices", "cost"] },
      { "key": "orders", "path": "/portal/orders", "label": "Your orders",
        "aliases": ["my orders", "order history"] },
      { "key": "signin", "path": "/login", "label": "Sign in",
        "aliases": ["sign in", "log in"] }
    ] }
```

Paths are **site-relative** — resolve against the current origin and navigate
client-side. `signin` and `orders` keys are guaranteed to exist (login deep-link,
order-status flow).

---

## 7. Tickets provider — escalate to a human

Replaces `agent/tickets.py`. Mika proposes only subject/category; she attaches
her **server-authored** transcript. Filing emails the ops inbox and creates an
admin-visible ticket.

```
POST /api/v1/agent/tickets                # user-scoped if signed in, else app-scoped
Headers: Idempotency-Key
Body:
{
  "subject": "Refund on order UT-ORD-10293",
  "category": "billing",                  # order|billing|technical|general|other
  "reason":   "agent_handoff",            # agent_handoff|verify_exhausted
  "customer_ref": "amina@example.com",    # optional; for anonymous reference
  "session_ref": "<mica-session-uuid>",
  "transcript": [
    { "role": "user",  "text": "I need a refund", "at": "…" },
    { "role": "agent", "text": "I've opened a ticket…", "at": "…" }
  ]
}
→ 201 { "ticket_id": "tkt_5567", "ref": "UT-5567", "status": "open" }
```

- Read `ref` back to the customer. Send an `Idempotency-Key` so a retried
  escalation (e.g. on `reason=verify_exhausted`) doesn't double-file.
- `GET /api/v1/agent/tickets/UT-5567` → `{ ticket_id, ref, status }` for read-back.
- `422 invalid_params` if `subject` is empty or `category`/`reason` is off-list.

---

## Provider → endpoint map

| Mica module / tool | Backend endpoint | Scope |
|---|---|---|
| `agent/identity.py` | `GET /_allauth/browser/v1/auth/session` (+ `GET …/customers/me`) | session |
| `agent/catalog.py` | `GET /api/v1/agent/services` (+ `/{key}`) | app |
| `agent/pricing.py` | `POST /api/v1/agent/services/{key}/quote` | app¹ |
| `create_order` / status | `POST /api/v1/agent/orders`, `GET …/orders/mine`, `GET …/orders/{ref}` | user |
| `agent/kb.py` | `GET /api/v1/agent/kb/articles` | app |
| `agent/sitemap.py` | `GET /api/v1/agent/sitemap` | app |
| `create_ticket` | `POST /api/v1/agent/tickets` (+ `GET …/tickets/{ref}`) | user/app |

¹ Quotes are app-scoped today (pricing is not per-customer). If that changes,
the quote endpoint becomes user-scoped — forward `X-UT-Session` and the backend
will price per user; no shape change.

---

## Guardrails to preserve (unchanged on Mica's side)

- **The model never touches the backend directly.** It proposes a tool + args;
  Mica's loop validates, calls these endpoints, and verifies the result.
- **Whitelists hold.** Service keys, KB keys, sitemap keys are closed sets the
  backend defines and the model only selects from.
- **Deterministic money holds.** Price flows quote → order; no request carries a
  model-chosen amount, and Mika never renders a price the backend didn't return.
- **Audit holds.** Every backend call is one loop step in the append-only log.
- **Dev/test stays keyless.** `URBANTRENDS_API_BASE` unset → static modules.

---

## Reference implementation checklist (Mica repo)

1. Add a thin `UrbanTrendsClient` (base URL + bearer key + optional
   `X-UT-Session` + ~4 s timeout + `Idempotency-Key` helper). Parse the
   `{error:{code,…}}` envelope into typed failures.
2. Behind each provider interface, add an HTTP-backed impl selected when
   `URBANTRENDS_API_BASE` is set; keep the static module as the default.
3. Honour `ETag` on catalog/kb/sitemap (cache the payload + `If-None-Match`).
4. Map error codes → existing behaviours: `401`→login deep-link,
   `422 invalid_params`→re-collect fields, `409 quote_expired`→re-quote,
   `quote_unavailable`→human quote-request, timeout/5xx→degrade safely.
5. Store `quote_id` on the draft; pass it to `POST /orders`. Never persist or
   send an amount.
```
