# Project Proposal — UrbanTrends Agentic Customer Bot

**Codename:** Concierge (working name)
**Entity:** Genmars Tech Limited / UrbanTrends
**Status:** Draft v1 — Internal pilot
**Author:** Edwin Muchemi Wamuyu
**Date:** July 2026

---

## 1. Summary

An agentic customer-facing bot embedded on urbantrends.dev (and later, client products like Conduit and RentFlow) that doesn't just answer questions — it **acts**. It can log a customer in, walk them through the site, place an order for a product/service, pop dynamic forms to collect information, and resolve issues one-on-one.

For the pilot phase it runs as an **internal tool only**, so we can observe behavior, tune guardrails, and validate the action loop before exposing it to real customers.

## 2. Problem

Right now, a visitor on urbantrends.dev who wants to buy a service has to: find the right page, understand the offering, fill a contact form, and wait for a manual reply. Every step is a drop-off point. Support is also fully manual — a solo-founder bottleneck.

## 3. Goals

- Convert site visitors into qualified orders with zero human intervention for the happy path.
- Reduce time-to-first-response for support from hours to seconds.
- Build a reusable agent core that can later be white-labeled into Conduit tenant portals.

**Non-goals (v1):** payments execution, refunds, account deletion, anything irreversible without human approval.

## 4. How it works — the agent loop

The agent follows a strict four-step loop on every interaction:

1. **Wait** — idle until a user message or event arrives.
2. **Act** — interpret the request, pick a tool (login, navigate, order, form, ticket), execute it against the backend.
3. **Verify** — check the tool result against the original intent. Did the order actually get created? Did login succeed? If not, retry or escalate.
4. **Respond & log** — reply to the user and write an append-only event record (intent, tool calls, results, outcome).

The verify step is what makes this *agentic* rather than a chatbot: the agent is accountable for outcomes, not just replies.

## 5. Capabilities (v1 scope)

| Capability | What the agent does | Backend action |
|---|---|---|
| **Customer login** | Recognises whether the visitor is signed in on urbantrends.dev and greets them accordingly; if not, deep-links them to the site's sign-in page | **Verifies the host-site session** (headless django-allauth — passkey / email-code) by introspecting its session endpoint; Mika never registers users or issues codes. allauth stays the single source of truth |
| **Site navigation** | Answers "where do I find X", deep-links the user to the right page/section | Read-only site map + `navigate` tool that the widget executes client-side |
| **Ordering** | Gathers requirements conversationally, quotes a price, creates the order | LLM gathers requirements → **deterministic pricing rules engine** computes the quote (the model never invents prices) → order record created in `pending` state |
| **Dynamic forms** | Pops a form in/out of the chat when structured info is needed (name, KRA PIN, project brief, etc.) | JSONB-defined form schemas rendered by the widget; submissions validated server-side |
| **Issue resolution** | Handles support queries one-on-one; resolves from a knowledge base or escalates | Creates a ticket with full conversation context when it can't resolve |

## 6. Architecture

```
┌─────────────────────────────┐
│  Next.js chat widget         │  embeddable <script>, forms UI,
│  (urbantrends.dev)           │  client-side navigate actions
└──────────────┬──────────────┘
               │ WebSocket / SSE
┌──────────────▼──────────────┐
│  Django + DRF agent service  │  session mgmt, tool registry,
│  (agent orchestrator)        │  verify step, rate limiting
└───────┬──────────┬──────────┘
        │          │
┌───────▼───┐ ┌────▼──────────┐
│ Claude API │ │ Action layer   │  host-auth check, orders, pricing
│ (tool use) │ │ (Django apps)  │  rules engine, tickets, forms
└───────────┘ └────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ PostgreSQL + Redis   │  append-only AgentEvent log,
        │                      │  session state, rate limits
        └─────────────────────┘
```

**Stack decisions:**
- **Orchestrator:** Django/DRF (fastest path — reuses RentFlow auth patterns, Celery for async tool calls). Rust/Axum considered but deferred; not the bottleneck at pilot scale.
- **LLM:** Claude via Anthropic API with tool use. The model only ever calls whitelisted tools with validated schemas — it cannot touch the DB directly.
- **State:** Every agent action written to an **append-only `AgentEvent` table** (same pattern as OnboardKit's application events). Full replayability and audit trail.
- **Widget:** Next.js/TypeScript, distributed as an embeddable snippet — same delivery model planned for SiteChat, so the embed infrastructure is shared.
- **Deploy:** Docker Compose on the existing Hetzner box, Caddy-proxied, bound to 127.0.0.1, shipped via GitHub Actions → GHCR.

## 7. Persona — the anime mascot avatar

The agent is not presented as a chat bubble. It appears as **"Mika from UrbanTrends"** — a small original anime-style character (~90–120px) floating bottom-right of the page. The character is the interface: the chat panel, forms, and navigation hints all pop out from her.

**Character:** Mika — black bob with bangs, round red-tinted sunglasses, red earring, black shirt; black + deep red palette matching the UrbanTrends dark-first aesthetic. Personality: composed, capable, quietly friendly. Concept reference exists; production asset to be commissioned as a simplified/stylized original design (artist spec in `MIKA_CHARACTER_BRIEF.md`; full widget UI spec for Claude Design in `MIKA_CLAUDE_DESIGN_PROMPT.md`). Must be fully original for commercial use.

**Avatar states map directly onto the agent loop:**

| Loop step | Avatar state |
|---|---|
| Wait | Idle animation (blink, sway, occasional wave) |
| Act | Thinking pose (tool call in flight) |
| Verify | Checking/inspecting animation |
| Respond & log | Talking animation + speech bubble |
| Error/escalation | Apologetic pose, offers to create a ticket |
| Order confirmed | Celebration animation |

**Rendering options (in order of effort):**

1. **Sprite/Lottie state machine** — 6–8 short looping animations exported as Lottie or a sprite sheet, driven by a tiny state machine in the widget. Lightweight (<200KB), works everywhere. **← pilot choice.**
2. **Live2D Cubism Web SDK** — rigged 2D with head-tracking/parallax, breathing, lip flap. Premium feel, but adds SDK licensing and rigging cost. Upgrade path after pilot.
3. **VRM 3D (three.js)** — full 3D character. Heaviest payload; only worth it for a flagship marketing moment.

**UX rules:** character starts minimized; expands the chat panel on click; forms slide out of its speech bubble; navigation help = the character points and the page scrolls/deep-links; respects `prefers-reduced-motion` (falls back to static poses); never blocks content on mobile.

## 8. Guardrails

- **Deterministic money:** all prices and quotes come from the rules engine, never the model. The model's job is requirement-gathering only.
- **Tool whitelist + server-side validation:** every tool input re-validated in Django regardless of what the model sends.
- **Confirmation gates:** order creation and any state-changing action require explicit user confirmation in the widget before execution.
- **Rate limits:** per-session and per-IP (Redis), reusing the site's existing rate-limit patterns.
- **Prompt-injection posture:** user content is data, not instructions; system prompt pins the tool contract; no free-text execution paths.
- **Escalation path:** anything outside scope → ticket with transcript attached, human (me) notified.

## 9. Pilot plan (internal testing phase)

**Sequencing rule: build the agent first.** All agent phases (P1–P4) run with a plain placeholder widget (simple avatar circle + chat panel). Mika's visual design (Claude Design output + final animation assets) is produced in parallel and integrates only in P5, once complete. The agent never waits on design; design never blocks engineering.

**No time frames.** Phases are purely gate-driven: the moment a phase's gate passes, the next phase starts immediately. No scheduled durations, no idle gaps between phases.

| Phase | Gate to pass |
|---|---|
| **P1 — Loop skeleton** | Wait → act → verify → respond → log works end-to-end with a single dummy tool |
| **P2 — Login + navigation** | Host-site auth check (verify the urbantrends.dev session) and deep-link navigation working through the widget |
| **P3 — Ordering + forms** | Full order flow: conversation → dynamic form → rules-engine quote → pending order |
| **P4 — Support + escalation** | KB answers + ticket creation with transcript |
| **P5 — Mika integration** | Mika design complete (Claude Design screens + Lottie/sprite state assets); avatar states wired to the loop (idle/thinking/checking/talking/pointing/celebrating/apologetic); widget restyled to the site design system. **This phase only starts once the Mika design is finished — if P4's gate passes first, engineering proceeds to P6 hardening work in the meantime and circles back.** |
| **P6 — Hardening** | Rate limits, injection tests, audit log review, cost tracking |

Each phase is gate-driven: no moving forward until the gate passes (same discipline as the Keja/OnboardKit plans).

## 10. Success metrics (pilot)

- ≥ 90% of test orders created correctly without human correction.
- 100% of quotes match the rules engine (zero hallucinated prices).
- Verify step catches ≥ 95% of injected tool failures in testing.
- Median response latency < 3s for non-tool turns.
- Full audit trail reconstructable for any session from `AgentEvent` alone.

## 11. Risks

- **LLM cost creep** — mitigate with per-session token budgets and Haiku for routing/classification, Sonnet for the ordering conversation.
- **Prompt injection via user messages** — mitigated by tool whitelist, server-side validation, confirmation gates; red-team during P5.
- **Scope creep into payments** — explicitly out of v1; orders land in `pending` and M-Pesa collection stays in the existing manual/RentFlow flow.
- **Widget conflicts on client sites** (future) — shadow DOM isolation, learned from SiteChat embed work.
- **Character IP** — the mascot must be fully original with commercial rights secured in writing from the artist; anything resembling existing anime IP is a legal risk. Payload also kept under ~200KB so the avatar never slows the site.

## 12. Future direction

Once the pilot passes, the same agent core becomes: (a) the Conduit tenant-facing ordering agent, (b) a RentFlow tenant support agent, and (c) a sellable "agent add-on" for client sites — turning this internal tool into product-line leverage.

**Backend pricing integration.** The pilot's pricing rules and figures live in `agent/catalog.py` as illustrative in-code rates. Once the ordering tool is wired to the company's real pricing backend, quotes should be computed from the company's actual, live prices instead of the hard-coded rules — while keeping the deterministic-money guardrail intact: prices still come only from a server-side source of truth (now the backend), never from the model. Only the *source* of the numbers changes; `agent/pricing.py` stays the single, auditable engine and order tools still never accept or emit an amount.
