# BE-1 — Spine to Genesys (Profile, gx surface, verify-customer)

**Goal.** Put the first `/gx/` endpoints in front of the Customer Spine so Genesys can resolve a subscriber and verify identity, with flat contract-safe responses and exported data-action contracts. This is the layer Genesys actually binds to.

**Do not** build the network module, scenarios, admin UI, OIDC, bookings, or any domain verbs. Those are later phases. gx here is read + verify only.

## Prerequisites

- BE-0 signed off. `colima start` before `make up` (Colima does not auto-start on login).
- **Housekeeping from BE-0 sign-off:** convert the BE-0 seed pack from JSON to **YAML** (`pack.yaml`) and add `pyyaml`, per the locked "Seed / scenario pack format" decision. Re-run the seed gate to confirm counts and idempotency still hold. Do this first; it is a small carryover, not part of BE-1's gate.
- Read `../CLAUDE.md` and the Notion pages (hub, `01 Decisions log`, `02 Backend build`, `06 Issues & blockers`).

## Scope (in)

### 1. Identifier normalization (the load-bearing piece)
A single, table-driven, unit-tested function at the **gx boundary only** (for example `app/gx/normalize.py`). It takes the raw identifier Genesys sends and returns `(normalized_value, id_type)`.

- Handles the space-decoded `+` trap: a leading space where a `+` was expected (from an unencoded `+` in a query string) is treated as `+`.
- Normalizes phone/msisdn to E.164. A bare national number is resolved using the **tenant's country** (from tenant/pack config, not hardcoded).
- Email and `account_no` pass through unchanged, with `id_type` detected.
- Does **not** live in the core `/v1` resolver. `/v1` stays a faithful low-level view; gx owns the real-world messiness. (Locked decision, see `01`.)

Required test table (at minimum): `+447700900000`, `" 447700900000"` (space-decoded `+`), `447700900000`, `07700900000` (UK national), `alice@example.net`, an `account_no`, and an unparseable value (returns a clean "unrecognized" result, not a 500).

### 2. `GET /gx/customer-context`
Resolves a subscriber via the normalization function and returns **flat, contract-safe JSON** (no nested arrays):
```
{ found, party_id, display_name, tenant_slug, tier, verified, last_channel, id_type_resolved }
```
- `verified` is `false` at the context stage (verification is a separate call).
- Not found returns `{ "found": false }` with 200, not an error, so Genesys can branch on it.
- Cross-tenant lookups must not leak (reuse BE-0 tenant scoping).

### 3. `POST /gx/verify-customer`
Input `{ identifier, factor_type, factor_value }`. Normalizes the identifier, recomputes `sha256("<factor_type>:<value>")`, compares to the stored hash, returns flat:
```
{ verified, party_id, masked_name }
```
- Wrong factor returns `{ "verified": false }` (200), no detail leak.
- `masked_name` format comes from config.

### 4. Profile module + `/v1`
Add the internal profile rollup that `customer-context` flattens from. Keep the rich shape under `/v1` (extend BE-0's `/v1/parties` as needed); gx wraps and flattens it. No nested arrays escape through gx.

### 5. Exported data-action contracts
Generate the Genesys **Web Services** data-action input/output contract JSON for each gx endpoint into `backlot/contracts/` (one file per endpoint). Contracts must be flat (no nested arrays), typed, and ready to import. These are what GX-B binds to against base URL `https://backlot-api.krishharness.com`.

## Config-over-code checkpoints
- Tenant country for national-number normalization is pack/tenant config, not a literal.
- `masked_name` format is config.
- No industry-specific logic; this is generic identity + profile.

## Acceptance gate (all must pass)
- [ ] Normalization unit tests cover the full case table above, including the space-decoded `+`.
- [ ] `GET /gx/customer-context` returns flat JSON; a test asserts **no nested arrays** in the response. Found, not-found (`{found:false}`, 200), and cross-tenant-no-leak all covered.
- [ ] `POST /gx/verify-customer` passes happy path and returns `{verified:false}` on a wrong factor, recomputing the BE-0 hash.
- [ ] `backlot/contracts/` contains one importable, flat contract file per gx endpoint.
- [ ] gx endpoints require `X-API-Key` (401 without).
- [ ] `pytest` green, `ruff` clean, `mypy app` clean.
- [ ] `scripts/demo_be1.sh` resolves a seeded Northwind subscriber via `/gx/customer-context` and verifies a factor, end to end.
- [ ] `/docs` shows the new `/gx/*` paths.

## Curl walkthrough (`demo_be1.sh` should cover)
```bash
BASE=http://localhost:8000
# resolve (note the + must be percent-encoded as %2B on the wire)
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/customer-context?identifier=%2B447700900000"
# not found
curl -s -H "X-API-Key: $API_KEY" "$BASE/gx/customer-context?identifier=%2B447700900999"
# verify
curl -s -H "X-API-Key: $API_KEY" -X POST "$BASE/gx/verify-customer" \
  -H "Content-Type: application/json" \
  -d '{"identifier":"+447700900000","factor_type":"pin","factor_value":"1234"}'
```

## Session end
Update Notion `02 Backend build` (BE-1 status + notes), append each new gx endpoint to `07 API registry`, log any new decision to `01`, and any blocker to `06`. If the Notion MCP is not configured in Claude Code, print a `## Notion update` block for the human to paste.

## Definition of done
Gate passes and Krish signs off. Then request the BE-2 brief (Network & Devices, the WiFi engine).
