# BE-3 — Scenario engine + admin UI

**Goal.** Make demos deterministic and repeatable without a full re-seed. A declarative scenario engine stages and resets state on command, and a thin admin UI lets you browse subscribers, apply a scenario, and watch state change live while you present.

**Do not** build events/telemetry (BE-4) or any Banking/Insurance modules (BE-5). No new gx endpoints for Genesys here; the scenario controls are admin-only.

## Prerequisites
- BE-2 signed off. `colima start` before `make up`.
- Read `../CLAUDE.md` and the Notion pages (hub, `01`, `02`, `06`, `07`).

## The requirement that defines this phase
An operator can run the WiFi demo repeatedly using **apply/reset alone, with no `make seed` between takes**. Stage the fault, walk the fixes (which mutate state), reset, repeat. That is the acceptance bar; the baseline model below is the means.

## Scope (in)

### 1. Scenario engine
- **Declarative YAML scenario packs**, per tenant, at `app/scenarios/packs/<tenant>/*.yaml` (YAML per the locked pack-format decision). A pack names a target state as a set of field-setters over existing entities (match + set), not code.
- **`reset()`**: restore the tenant's seeded baseline in-place, fast and idempotent, without a full re-seed. This is the "between takes" button.
- **`apply(scenario_name)`**: mutate to the named staged state.
- **Event log**: every mutation (apply or reset) writes an entry the admin UI can show, so state changes are visible, not mysterious.
- **Tenant-scoped and isolated**: applying or resetting one tenant provably never touches another (same discipline as the BE-2 seed authority; test it).
- Baseline model is your call (healthy baseline + a `wifi_degraded` scenario, or degraded baseline + reset), as long as the repeatability requirement above holds and the WiFi demo's fault progression still reads band-stuck first.

### 2. Northwind scenario packs
At minimum: `wifi_degraded` (the demo fault: device_band_stuck + extender_flapping), `outage_in_area` (wan_degraded), and `healthy`. Each a YAML file. Adding a scenario must be a new file, not code.

### 3. Thin admin UI (Jinja + htmx)
- Lists subscribers for the tenant with key state (network health, current fault).
- Buttons per subscriber (or global): apply a scenario, reset. State updates visibly via htmx without a full page reload, so during a demo the audience sees the record change.
- Keep it thin. The value is watching state change, not a polished SPA. Server-rendered Jinja + htmx per the locked decision. Do not rabbit-hole on frontend.

### 4. Admin auth is separate from the Genesys key (non-negotiable)
- The admin UI and the `/admin/*` endpoints sit behind their own auth (basic auth or an admin token from `.env`), never the gx `X-API-Key`.
- The Genesys `X-API-Key` must **not** grant admin access, and the admin token must **not** grant gx access. Test both directions.

## Config-over-code checkpoints
- Scenarios are YAML packs. Adding one is a file.
- Field-setters match on entity attributes from config, no hardcoded subscriber IDs in engine code.
- Thresholds and fault definitions still live in `config_json.network` from BE-2; scenarios set state, they do not redefine detection.

## Acceptance gate (all must pass)
- [ ] `apply(wifi_degraded)` stages the fault; `net-diagnostics` reflects it (band-stuck first).
- [ ] `reset()` restores the baseline; `net-diagnostics` reflects baseline. Both idempotent.
- [ ] The full WiFi demo runs **repeatedly via apply/reset with no `make seed`** between takes.
- [ ] Event log records each apply and reset.
- [ ] Cross-tenant isolation: applying/resetting tenant A never mutates tenant B (tested).
- [ ] Admin UI lists subscribers, apply/reset work, and state updates live via htmx.
- [ ] Admin auth enforced; gx `X-API-Key` does not open `/admin/*`, and the admin token does not open `/gx/*` (both tested).
- [ ] Scenario packs are YAML under `app/scenarios/packs/northwind/`.
- [ ] `pytest` green, `ruff` clean, `mypy app` clean.
- [ ] `scripts/demo_be3.sh` clean.
- [ ] `/docs` reflects the `/admin/*` control endpoints.

## Curl / flow walkthrough (`demo_be3.sh`)
```bash
BASE=http://localhost:8000
# reset to baseline, stage the fault, verify, fix, confirm, reset again — no re-seed
curl -s -u "$ADMIN" -X POST "$BASE/admin/scenario/reset"
curl -s -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}'
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/net-diagnostics?identifier=%2B447700900000"   # device_band_stuck
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/device-action" -H "Content-Type: application/json" -d '{"identifier":"+447700900000","action":"band-steer","target":"<device_id>"}'
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/device-action" -H "Content-Type: application/json" -d '{"identifier":"+447700900000","action":"reboot-extender","target":"<ap_id>"}'
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/net-status?identifier=%2B447700900000"          # healthy
curl -s -u "$ADMIN" -X POST "$BASE/admin/scenario/reset"                                     # back to baseline
# negative checks
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $API_KEY" -X POST "$BASE/admin/scenario/reset"   # expect 401/403
curl -s -o /dev/null -w "%{http_code}\n" -u "$ADMIN" "$BASE/gx/net-status?identifier=%2B447700900000"     # expect 401/403
```

## Session end
Update Notion `02` (BE-3 status + notes), append any `/admin/*` control surface to `07` (note it is admin-auth, not gx), record scenario pack names, log decisions to `01`, blockers to `06`. Print a `## Notion update` block if the Notion MCP is not configured.

## Definition of done
Gate passes and Krish signs off. Then request the BE-4 brief (events / webhooks: telemetry emitter for later proactive reach, and CSAT write-back), which is the last backend phase before the M1 WiFi demo is fully wired in Genesys.
