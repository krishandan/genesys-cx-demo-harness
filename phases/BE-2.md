# BE-2 — Network & Devices (the WiFi self-healing engine)

**Goal.** The module that mimics a telco's device-management platform (ACS / mesh vendor API), so AVA can diagnose a home network, act on it with consent, and confirm recovery. Plus the Northwind seed with a deterministic degraded subscriber the demo runs against.

**Do not** build the scenario engine or admin UI (BE-3), events/telemetry (BE-4), or any Banking/Insurance modules. BE-2 seeds the degraded state directly; generalized apply/reset comes in BE-3.

## Prerequisites
- BE-1 signed off. `colima start` before `make up`.
- Read `../CLAUDE.md` and the Notion pages (hub, `01`, `02`, `06`, `07`).

## The design point that governs BE-2: diagnostics is a flat verdict, not raw topology

A home network is inherently a list of devices, radios, and APs, which is exactly the nested-array shape gx cannot return. So follow the BE-1 pattern:

- **`/gx/net-diagnostics`** returns a **flat verdict**: the module runs fault detection internally and returns the decision AVA needs, not the raw graph. Fields like `fault_type`, `primary_target`, `primary_target_kind`, `recommended_action`, `wan_ok`, `worst_device_band`, `worst_device_rssi`, `extender_status`. One flat object, branchable in a flow.
- **`/gx/net-status`** returns the flat current state for post-action confirmation.
- **`/gx/device-action`** is the hybrid action endpoint (verbs below).
- **`/gx/devices`** (optional, only if AVA needs to enumerate) may return a **top-level array of flat device objects**. Top-level array is allowed; an array nested inside an object property is not.
- **`/v1/network?identifier=`** is the rich nested truth that gx flattens.

If AVA needs to name the bad device to the customer, put that name in the flat verdict (`primary_target_label`), don't make the flow walk a topology.

## Scope (in)

### 1. Data model + migration
Network & Devices entities, all carrying `party_id` + `tenant_id`, tenant-scoped:
- `gateway` (per subscriber: model, wan_status, uptime_s)
- `radio` (band 2.4/5/6GHz, channel, utilization)
- `access_point` / mesh node (kind: gateway|extender|ap, status: online|flapping|offline, backhaul_quality)
- `connected_device` (label, mac, connected_ap, band, rssi, steer_eligible)

### 2. Fault detection (service)
Given a subscriber's topology, compute the flat verdict. Detect at least: `device_band_stuck` (a steer-eligible device on 2.4GHz with rssi below the poor threshold while 5GHz is available), `extender_flapping`, `wan_degraded`, and `none`. Thresholds (poor-rssi cutoff, flapping definition) are **config**, not magic numbers.

### 3. gx endpoints
`GET /gx/net-diagnostics`, `GET /gx/net-status`, `POST /gx/device-action`, optional `GET /gx/devices`, and rich `GET /v1/network`. All gx responses flat; contracts generated and drift-tested (BE-1 generator).

### 4. device-action verbs
`POST /gx/device-action {action, target, params}` where action ∈ `band-steer` | `reboot-extender` | `reboot-ap`:
- `band-steer {target: device_id}`: move a steer-eligible device 2.4 → 5GHz; update its band and rssi; clears `device_band_stuck`.
- `reboot-extender {target: ap_id}`: extender goes offline then online; clears `extender_flapping`.
- `reboot-ap {target: ap_id}`: AP reboots; connected devices reattach.
Each **mutates state** so a follow-up `net-status` / `net-diagnostics` reflects the change. Return a flat `{ok, action, target, result_summary, fault_cleared}`. Unknown target or wrong action returns a clean flat 4xx error, never a 500.

> reboot-ap note: rebooting the AP the customer is connected through would drop their session. That choreography (offer to move to mobile data first, then resume) is the **Genesys** side, GX-D, not the backend. The backend just flips the AP offline→online and reattaches devices. Do not model client connectivity here.

### 5. Northwind seed
Seed one clearly-identified **demo subscriber** in the degraded state that drives the WiFi demo: WAN healthy, a 5GHz-capable phone pinned to 2.4GHz with poor rssi, and a mesh extender flapping. Seed a few healthy subscribers for realism. Deterministic. Record the demo subscriber's identifier and its staged fault in Notion `07` seed keys.

## Config-over-code checkpoints
- Fault thresholds are pack/module config.
- The degraded topology is seed/pack data, not code.
- Device and AP model names come from the pack.
- Adding a fault type should be a detector + verdict field, not a rewrite.

## Acceptance gate (all must pass)
- [ ] Migration applies clean from an empty volume.
- [ ] `net-diagnostics` for the demo subscriber returns the seeded fault as a flat verdict; a healthy subscriber returns `fault_type: none`.
- [ ] Each `device-action` verb mutates state; a follow-up `net-diagnostics`/`net-status` shows the fault cleared or state changed.
- [ ] Unknown target or wrong action returns a clean flat 4xx, not a 500.
- [ ] gx responses are flat (test-asserted no nested arrays); contracts generated and the drift test passes.
- [ ] Cross-tenant lookups and actions do not leak or mutate across tenants.
- [ ] Re-seed restores the degraded baseline (full apply/reset scenarios are BE-3; note this in the seed).
- [ ] `pytest` green, `ruff` clean, `mypy app` clean.
- [ ] `scripts/demo_be2.sh` runs: resolve subscriber → diagnostics (fault) → band-steer → reboot-extender → net-status shows recovery.
- [ ] `/docs` shows the new `/gx/*` and `/v1/network` paths.
- [ ] Notion `07` seed keys records the demo subscriber identifier and its staged fault.

## Curl walkthrough (`demo_be2.sh` should cover)
```bash
BASE=http://localhost:8000
ID=%2B447700900000   # the degraded demo subscriber (use the real seeded value)
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/net-diagnostics?identifier=$ID"      # fault: device_band_stuck (or extender_flapping)
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/device-action" \
  -H "Content-Type: application/json" -d '{"identifier":"+447700900000","action":"band-steer","target":"<device_id>"}'
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/device-action" \
  -H "Content-Type: application/json" -d '{"identifier":"+447700900000","action":"reboot-extender","target":"<ap_id>"}'
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/net-status?identifier=$ID"            # recovered
```

## Session end
Update Notion `02` (BE-2 status + notes), append the new gx endpoints to `07`, record the demo subscriber in `07` seed keys, log decisions to `01`, blockers to `06`. Print a `## Notion update` block if the Notion MCP is not configured in Claude Code.

## Definition of done
Gate passes and Krish signs off. Then request the BE-3 brief (scenario engine + admin UI), which generalizes the seeded degraded state into apply/reset so demos are deterministic and repeatable.
