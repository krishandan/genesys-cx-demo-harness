# BE-5 — Telco demo completion (devices, offers, orders) + AVA-compliant contracts

**Goal.** Close the four backend gaps Demo 1 needs, and make every generated contract importable into Genesys and usable as an **AVA tool**. After this phase the backend is complete for Demo 1 end to end.

> Renumbering note: this phase was previously "Banking + Insurance + OIDC". That work moves to **BE-6**. Demo 1 needs telco depth first.

**Do not** build Banking/Insurance packs, the OIDC provider, or any new industry. Telco only.

## Prerequisites
- BE-4 signed off. `colima start` before `make up`.
- Read `../CLAUDE.md` and Notion (hub, `01 Decisions log`, `02 Backend build`, `06 Issues & blockers`, `07 API registry`).
- Note the **AVA schema constraints** in `01` before designing any output shape.

## Context: what these endpoints feed

Demo 1 is built on **AVA (Genesys Agentic Virtual Agent)**. AVA tools *are* data actions, so every gx endpoint here becomes a tool the agent can call. Two consequences drive the design:

1. **AVA silently rejects non-compliant tools.** The tool disappears on save with no error. Compliance is not optional.
2. **The agent reads your field names and descriptions to decide when to call a tool.** Descriptions are functional, not documentation.

## AVA compliance rules (apply to every gx endpoint, new and existing)

Output schemas must NOT contain: `oneOf`/`anyOf`/`allOf`, `if`/`then`/`else`, `dependencies`, `$ref`, `not`, `const`, empty objects (objects with no properties), tuple validation (multiple schemas in `items`), or **nested arrays** (`items` cannot be of type `array`).

Additional hard rules:
- **No dots in any property name.** Underscores only. (A community-confirmed failure: output fields containing `.` caused the tool to vanish on save.)
- A **top-level array of flat objects is allowed** — that is how `/gx/devices` must be shaped.
- Property names start with a letter; letters, numbers, hyphens, underscores only.
- Every output property needs a **clear, agent-facing description**. The agent uses these to reason.

Add a test that asserts these rules across all generated contracts, so a future endpoint cannot silently break AVA.

## Scope (in)

### 1. Contract generator fixes (do this first — it unblocks Genesys work)
- Emit `"actionType": "custom"` alongside `"integrationType"`.
- Drop the optional `tenant` input and the `X-Tenant: ${input.tenant}` header. An unsupplied optional input can render the literal `${input.tenant}` in Velocity and break the lookup. Single-tenant box; `DEFAULT_TENANT` covers it. (Re-add as a **required** input in BE-6 when multi-tenant lands.)
- Use `${esc.url(input.identifier)}` in `requestUrlTemplate` query params so a `+` in E.164 is percent-encoded rather than decoding to a space.
- For GET actions, drop `requestTemplate` if it is spurious (GET has no body). For POST actions, build the body with `esc.jsonString` escaping.
- Add the AVA-compliance validation described above to generation; fail generation on violation.
- Regenerate all contracts; drift test must pass.

### 2. `GET /gx/devices?identifier=`
Top-level array of flat device objects, so the agent can match a device the customer *names* ("my daughter's iPad").
```
[ { device_id, label, kind, band, rssi, ap_label, steer_eligible, status_summary }, ... ]
```
- `label` is the human name ("Ella's iPad").
- `status_summary` is a short plain-English health phrase the agent can speak ("weak signal on the slower band").
- Unknown identifier → empty array (not an error).
- Descriptions must make clear this is for matching a customer-named device.

### 3. `GET /gx/offers?identifier=`
Flat, single best eligible offer:
```
{ found, offer_id, name, price_gbp, reason, eligible }
```
- `reason` is why this customer is eligible in plain English ("covers the weak-signal area upstairs").
- Eligibility derives from seeded state (e.g. has a flapping/edge-of-range extender), not a hardcoded id.
- Not eligible → `{found: true, eligible: false, ...}` with empty offer fields, same key set both ways (BE-1 rule).

### 4. `orders` module + `POST /gx/order-action`
Follows the established hybrid pattern (one action endpoint per module, verbs register handlers — same as `device-action`).
- Verbs: `place`, `send-confirmation`.
- `place {identifier, offer_id}` → `{ok, order_id, status, eta_text}`. Persists an order row.
- `send-confirmation {identifier, order_id}` → `{ok, sent_to_masked, message_ref}`. Records a `order.confirmation_sent` event; `sent_to_masked` is a masked email ("e••••@example.net") so the agent can confirm without reciting a full address.
- Both must be **idempotent per order** (re-running `place` for the same offer in the same session must not create a second order).
- Bad input → flat 4xx via `JSONResponse` (never `HTTPException` — it nests under `detail`).

### 5. Seed enrichment (Northwind)
- **5-digit PIN** (was 4). Update the pack; the demo PIN must be stable and documented in `07`.
- **Named devices with family labels** on the demo subscriber: at minimum a phone, a laptop, and **"Ella's iPad"**. The iPad is the faulted device in `wifi_degraded` (2.4GHz, ≈ −78 dBm) so the customer's complaint and the diagnostic verdict align.
- Healthy devices alongside it, so "which device?" and a named-healthy-device answer are both meaningful.
- An **email address** on the demo subscriber for the confirmation step.
- **Offer eligibility** state (e.g. an extender at edge of range) driving `/gx/offers`.

### 6. Scenario updates
- `wifi_degraded` must fault **Ella's iPad** specifically (not an arbitrary device), so the narrative lands.
- Keep fault precedence: band-stuck surfaces before extender-flapping.
- `reset` must clear orders and order events as well (extends the BE-4 rule) so a demo take starts clean.

## Config-over-code checkpoints
- Device labels, offer catalogue, and eligibility rules are **pack config**, not code.
- Adding an offer is a pack edit.
- No hardcoded subscriber ids anywhere in module logic.

## Acceptance gate
- [ ] All regenerated contracts import into Genesys without the `actionType` error.
- [ ] An automated test asserts AVA schema compliance across every contract (no forbidden keywords, **no dots in property names**, no nested arrays).
- [ ] `/gx/devices` returns a top-level array of flat objects; unknown identifier → empty array; `Ella's iPad` present and faulted under `wifi_degraded`.
- [ ] `/gx/offers` returns a flat single offer; eligible and not-eligible responses share an identical key set.
- [ ] `/gx/order-action` `place` then `send-confirmation` succeed, persist, and are idempotent; bad input → flat 4xx.
- [ ] `reset` clears orders and order events; a second demo take starts clean.
- [ ] 5-digit PIN verifies via `/gx/verify-customer`.
- [ ] Cross-tenant isolation holds on all new endpoints.
- [ ] `pytest` green, `ruff` clean, `mypy app` clean.
- [ ] `scripts/demo_be5.sh` runs the full Demo-1 backend arc: resolve → verify PIN → devices (match iPad) → diagnostics → band-steer → net-status → offers → place → send-confirmation.
- [ ] `/docs` shows the new paths.

## Session end
Update Notion `02` (BE-5 status + notes), append every new endpoint to `07` **with the demo PIN and device labels in seed keys**, log decisions to `01`, blockers to `06`. Print a `## Notion update` block if the Notion MCP is not configured.

## Definition of done
Gate passes and Krish signs off. Backend is then **complete for Demo 1**; remaining work is Genesys config and FE-2.
