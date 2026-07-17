# BE-4 — Events, CSAT write-back, telemetry seam

**Goal.** Give the harness a real interaction history and a place for Genesys to write results back, and build (but do not yet wire) the telemetry seam that a future proactive flow will consume. This closes the BE-1 carryover where `last_channel` was derived because no event history existed, and it is the last backend piece before the M1 WiFi demo is wired in the Genesys UI.

**Do not** build the proactive outbound push to Genesys (that is GX-C, post-M1, and needs confirmed box outbound), Open Messaging signature validation (Demo 4), or any Banking/Insurance modules (BE-5).

## Prerequisites
- BE-3 signed off. `colima start` before `make up`.
- Read `../CLAUDE.md` and the Notion pages (hub, `01`, `02`, `06`, `07`).

## Scope framing: M1 is inbound
The WiFi demo is customer-initiated, so nothing here pushes to Genesys. Two directions only:
- **Inbound write-back** (Genesys to Backlot, over the gx `X-API-Key`): interaction events and CSAT.
- **Internal emit + stored feed**: telemetry the network module raises, stored and readable, as the seam GX-C will later consume. Built and tested now; not consumed by Genesys in M1.

## Scope (in)

### 1. Event store
A generic `event` table, tenant- and party-scoped: `kind` (string) + a JSONB `payload`, plus `channel`, `occurred_at`, optional `conversation_ref`. Adding an event kind must not need a migration (kind + payload), while gx responses over it stay flat.

### 2. CSAT write-back (gx)
`POST /gx/csat {identifier, score, comment, conversation_ref}` stores a CSAT event, returns flat `{ok, party_id, stored}`. Bad score returns a flat 4xx. Auth is the gx `X-API-Key` (for M1 this is sufficient; third-party webhook signature validation is a Demo 4 concern, note it, do not build it).

### 3. Interaction events (gx) and real `last_channel`
`POST /gx/interaction-event {identifier, channel, kind}` records an interaction. Then update `/gx/customer-context` so `last_channel` comes from **real interaction history when it exists**, falling back to the BE-1 spine derivation when there is none. A test must show `last_channel` is derived before any event and sourced from the event after one.

### 4. Telemetry seam (built, not wired)
When a network fault is present or staged (for example applying `wifi_degraded`), the network module emits a `network.degraded` telemetry event for that subscriber into the event store. Expose a flat, readable feed (`GET /gx/telemetry` or `/admin/events` filtered) that a future proactive Genesys workflow can poll. No outbound push in M1.

### 5. Admin UI
Extend the thin admin events view to show interactions, CSAT, and telemetry (newest first). Keep it thin.

### 6. Contracts
Generate flat, drift-tested contracts for the new gx endpoints.

## Config-over-code checkpoints
- Event kinds are data (`kind` + JSONB), not new tables or branches.
- Telemetry emission is driven by the fault state, not hardcoded to one subscriber.
- No industry-specific logic; events are generic.

## Acceptance gate (all must pass)
- [ ] `POST /gx/csat` stores a CSAT event; it is readable back; response is flat; bad score returns a flat 4xx.
- [ ] `POST /gx/interaction-event` records an interaction.
- [ ] `last_channel` in `customer-context` is derived before any event and sourced from the recorded event after one (test both states).
- [ ] Applying `wifi_degraded` emits a `network.degraded` telemetry event, visible in the feed.
- [ ] A new event kind can be added without a migration; gx responses over events stay flat (no nested arrays; test-asserted).
- [ ] Cross-tenant isolation on all event reads/writes.
- [ ] gx `X-API-Key` enforced; `/admin` events view stays behind admin auth.
- [ ] Contracts generated and the drift test passes.
- [ ] `pytest` green, `ruff` clean, `mypy app` clean.
- [ ] `scripts/demo_be4.sh` clean.
- [ ] `/docs` shows the new `/gx/*` write-back paths.

## Curl walkthrough (`demo_be4.sh`)
```bash
BASE=http://localhost:8000
ID=%2B447700900000
# last_channel derived (no events yet)
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/customer-context?identifier=$ID"
# record an interaction, then last_channel comes from it
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/interaction-event" -H "Content-Type: application/json" -d '{"identifier":"+447700900000","channel":"webmessaging","kind":"inbound"}'
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/customer-context?identifier=$ID"
# CSAT write-back
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/csat" -H "Content-Type: application/json" -d '{"identifier":"+447700900000","score":5,"comment":"fixed my wifi","conversation_ref":"abc123"}'
# telemetry seam: staging the fault emits an event
curl -s -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}'
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/telemetry?identifier=$ID"
```

## Session end
Update Notion `02` (BE-4 status + notes), append the new gx endpoints to `07`, close the BE-1 `last_channel` carryover, log decisions to `01`, blockers to `06`. Print a `## Notion update` block if the Notion MCP is not configured.

## Definition of done
Gate passes and Krish signs off. At that point the **backend gx surface for M1 is complete**. The next work is Genesys UI wiring (GX-A/B/D/E) and the frontend (FE-2 Messenger embed), not another backend phase. BE-5 (Banking + Insurance + OIDC) comes after the WiFi demo is running end to end.
