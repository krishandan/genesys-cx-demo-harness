# Backlot

A reusable backend harness for Genesys Cloud demos. It exposes a stable set of APIs and
dummy customers so that demo work happens in the Genesys UI, not here.

New customers, industries, and scenarios are **data, not code**: a new telco is a new
seed pack, same code.

- **Tenant** = the Genesys customer (a telco, a bank, an insurer).
- **Subscriber / end customer** = that tenant's customer, the person who messages in.

Phase briefs live in `phases/`. This README covers **BE-0 — Foundations** (app skeleton,
API-key auth, the Tenant + Customer Spine, migrations, seed framework), **BE-1 — Spine
to Genesys** (the `/gx/` surface, identifier normalization, verify-customer, exported
data-action contracts), **BE-2 — Network & Devices** (the WiFi self-healing engine), and
**BE-3 — Scenario engine + admin UI** (stage and reset demo state on command).

## Requirements

- Docker + Docker Compose
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/) (only for host-run tests and linting)

## Local run

```bash
colima start   # only if `docker info` fails; Colima does not auto-start on login
make up        # copies .env.example → .env, builds, starts api + db
make seed      # seeds the Northwind Mobile pack (idempotent)
make demo      # the BE-0 curl walkthrough
make demo-be1  # the BE-1 gx walkthrough
make demo-be2  # the BE-2 WiFi self-healing walkthrough
make demo-be3  # the BE-3 scenario engine walkthrough
```

Then:

- **Admin UI: <http://localhost:8000/admin/>** — stage and reset demo state
- Health: <http://localhost:8000/health>
- OpenAPI docs: <http://localhost:8000/docs>

`make up` runs `alembic upgrade head` inside the api container on start, so a fresh
volume comes up migrated.

Other targets: `make down`, `make logs`, `make build`, `make migrate`, `make check`.

### Tests and static checks

```bash
make venv        # create .venv and install dev deps (once)
make check       # ruff + mypy + pytest
```

`pytest` runs on the host against a `backlot_test` database, which it drops and
recreates through the real Alembic migration on each run. It needs Postgres reachable
on `localhost:5432`; `docker-compose.override.yml` publishes that port for local
development only (see [Deployment](#deployment)).

## Environment variables

Copy `.env.example` to `.env`. Nothing below is hardcoded in Python — 12-factor, so the
same image runs on a laptop, on Unraid, or on AWS.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `local` | Environment label. |
| `APP_VERSION` | `0.1.0` | Reported by `/health`. |
| `API_KEY` | `dev-local-key-change-me` | Required in `X-API-Key` on every `/v1` and `/gx` call. **Change this off local.** |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `backlot-admin-change-me` | HTTP Basic for `/admin/*`. A separate trust domain from `API_KEY`. **Change both before exposing the tunnel.** |
| `DEFAULT_TENANT` | `northwind` | Tenant used when a request sends no `X-Tenant` header. |
| `DATABASE_URL` | `postgresql+psycopg://backlot:backlot@db:5432/backlot` | SQLAlchemy URL. `db` is the compose service name. |
| `GX_BASE_URL` | `https://backlot-api.krishharness.com` | Base URL baked into exported data-action contracts. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `backlot` | Postgres credentials. |
| `POSTGRES_DATA_PATH` | `./.data/postgres` | Host path backing the `pgdata` volume. On Unraid: `/mnt/user/appdata/backlot/postgres`. |
| `API_PORT` | `8000` | Host port for the api service. |
| `POSTGRES_PORT` | `5432` | Host port for Postgres — local development only. |
| `LOG_LEVEL` | `INFO` | Structured JSON logs to stdout. |
| `CLOUDFLARE_TUNNEL_TOKEN` | *(empty)* | Tunnel token. Blank locally; the service is inert. |

## Auth

Two separate trust domains. Neither credential grants the other's surface, and tests pin
both directions.

| Surface | Credential |
| --- | --- |
| `/gx/*`, `/v1/*` | `X-API-Key` header (`API_KEY`) — this is what Genesys holds |
| `/admin/*` | HTTP Basic (`ADMIN_USER` / `ADMIN_PASSWORD`) |
| `/health`, `/docs`, `/openapi.json` | public, so healthchecks and data-action imports work |

The separation is deliberate: if the Genesys key could reach `/admin`, a flow bug could
wipe demo state mid-presentation; if the admin login could reach `/gx`, an operator
credential would also be a customer-data credential.

Identity for M1 is **verify-then-context**: resolve the subscriber by identifier, then
carry identity as context. OIDC is deferred to BE-5.

## Tenant scoping

Every data query is scoped to the tenant resolved from the `X-Tenant` header, falling
back to `DEFAULT_TENANT`. An identifier belonging to one tenant will not resolve while
scoped to another — `tests/test_v1_core.py` pins that behavior.

## Seeding

```bash
make seed                                        # northwind
docker compose exec api python -m app.seed --tenant <slug>
```

Seeding is **deterministic** (Faker runs off a fixed seed held in the pack) and
**idempotent** (every primary key is a `uuid5` derived from the tenant slug and the
row's natural key, so a re-run merges onto the same rows).

It is also **authoritative for its tenant**: a re-seed prunes rows the pack no longer
describes, and never touches another tenant. This matters because row keys are digests
of natural keys — editing a pack value mints a new key, so without pruning the
superseded row would survive alongside its replacement.

The Northwind pack seeds one tenant plus 10 parties, each with three identities, one
hashed verification factor (`pin` = `1234`, so demos can assert it), and two contact
points.

### The WiFi demo subscriber

| | |
| --- | --- |
| Identifier | `+447700900000` (also resolvable by its email or `NW000000`) |
| Baseline | **Healthy.** The fault is staged by the `wifi_degraded` scenario, not seeded. |
| Verify factor | `pin` = `1234` |

Parties 1–3 get healthy networks for realism; the rest have no topology.

The baseline is deliberately healthy: `reset` restores it, scenarios stage faults on top.
A degraded baseline would make the seed accrete every demo's staged state once BE-5 adds
Banking and Insurance.

## Scenarios (staging a demo)

Open **<http://localhost:8000/admin/>**, or drive it with curl:

```bash
ADMIN=admin:backlot-admin-change-me
curl -su $ADMIN -X POST localhost:8000/admin/scenario/apply \
  -H 'Content-Type: application/json' -d '{"scenario":"wifi_degraded"}'
curl -su $ADMIN -X POST localhost:8000/admin/scenario/reset
```

| Scenario | Stages |
| --- | --- |
| `wifi_degraded` | The M1 demo: `device_band_stuck` + `extender_flapping`, WAN healthy |
| `outage_in_area` | `wan_degraded` — diagnostics escalates instead of suggesting in-home fixes |
| `healthy` | Heals the demo subscriber in place |

**Run a demo, then reset — no `make seed` between takes.** `reset` re-materializes the
seeded baseline in place, deriving it from the seed pack, so it cannot drift from what
the pack describes.

`apply` on a pack with `reset_first: true` resets first, so staging never depends on what
the last take left behind.

### Adding a scenario

Drop a YAML file in `app/scenarios/packs/<tenant>/`. No code, no deploy — the admin UI
picks it up as a button.

```yaml
name: my_scenario
title: My scenario
reset_first: true
subscribers:
  identifiers: ["+447700900000"]
steps:
  - description: What this step stages
    entity: connected_device     # gateway | access_point | radio | connected_device
    match: {seed_key: phone}     # the stable pack name, not a hardcoded id
    set:
      band: "2.4"
      rssi: -78
```

Scenarios only **set fields on rows that already exist** — they never create or delete,
and they cannot set `tenant_id`, `party_id`, or `seed_key` (which is what stops a
scenario reaching across tenants). They also don't redefine detection: the thresholds in
`config_json.network` decide what a staged state *means*.

Every apply and reset is recorded in an event log, shown in the admin UI.

### Adding a customer

Add `app/seed/packs/<slug>/pack.json` and run `python -m app.seed --tenant <slug>`. No
Python changes. The tenant's name, industry, and branding are pack values.

```yaml
tenant:
  slug: acme
  display_name: Acme Telecom
  industry: telco
  branding_json: {}
  config_json:
    country: GB            # resolves national numbers to E.164 at the gx boundary
    masked_name:           # shape of masked_name in verify-customer
      reveal_chars: 1
      mask_char: "*"
      mask_length: 3
seed:
  faker_seed: 20260716     # fixed → deterministic
  party_count: 10
  identities: [phone, email, account_no]
  verification:
    factor_type: pin       # dob | zip | pin | last4
    value_pattern: "1234"  # supports {index} for per-party values
  phone_pattern: "+447700900{index:03d}"
```

`config_json` is a deliberate JSONB bag: new tenant config is a pack edit, not a
migration.

### Synthetic data only

Never real PII. Seeded phone numbers sit in the `+447700900xxx` range Ofcom reserves for
fiction, and emails use the reserved `example.net` domain, so no seeded identifier can
reach a real person. Verification factors are stored only as SHA-256 digests.

## API

### `/gx/` — what Genesys binds to

Flat and contract-safe: every field is a scalar, always present, never null. Genesys
data action output contracts cannot express nested arrays, so nothing nested may escape
through gx.

| Method | Path | Auth | Returns |
| --- | --- | --- | --- |
| GET | `/gx/customer-context?identifier=` | `X-API-Key` | `{found, party_id, display_name, tenant_slug, tier, verified, last_channel, id_type_resolved}` |
| POST | `/gx/verify-customer` | `X-API-Key` | `{verified, party_id, masked_name}` |
| GET | `/gx/net-diagnostics?identifier=` | `X-API-Key` | The flat fault verdict — see below. |
| GET | `/gx/net-status?identifier=` | `X-API-Key` | Flat current network state, for confirming recovery. |
| POST | `/gx/device-action` | `X-API-Key` | `{ok, action, target, result_summary, fault_cleared}` |

Reads are 200 on the unhappy path — `found: false` / `verified: false` — so a flow
branches on a field instead of handling an error. A wrong factor returns no `party_id`
and no `masked_name`: the response never reveals whether the subscriber or the factor
was wrong.

`verified` on `customer-context` is always `false`. Context does not assert identity;
that is what `verify-customer` is for (**verify-then-context**, per the locked decision).

`device-action` is the exception: a bad request (unknown target, unknown verb, verb that
does not apply) returns a **flat 4xx** with the same key set, never a 500.

### `/v1/` — the rich internal surface

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | none | `{status, tenant_default, version}` |
| GET | `/v1/tenants` | `X-API-Key` | The tenant in scope for this request. |
| GET | `/v1/parties?identifier=` | `X-API-Key` | Resolve subscribers by exact identity value. |
| GET | `/v1/profile?identifier=` | `X-API-Key` | The rich rollup that `customer-context` flattens. |
| GET | `/v1/network?identifier=` | `X-API-Key` | The full home-network graph plus the verdict. |

`/v1` may nest freely. It does **not** normalize identifiers — it is a faithful
low-level view, and gx owns the messiness.

## Network & Devices (the WiFi engine)

A home network is a graph of gateways, radios, APs and devices — exactly the nested
shape gx cannot return. So the module runs fault detection internally and
`net-diagnostics` returns a **flat verdict**, not the topology:

```json
{
  "found": true, "party_id": "…",
  "fault_type": "device_band_stuck",
  "primary_target": "a2aefbbb-…", "primary_target_kind": "device",
  "primary_target_label": "Anne's Phone",
  "recommended_action": "band-steer",
  "wan_ok": true, "worst_device_band": "2.4", "worst_device_rssi": -78,
  "extender_status": "flapping"
}
```

The verdict *names* the thing to act on, so a flow never walks a topology: pass
`primary_target` straight back as `device-action`'s `target`.

### Faults

| fault_type | Fires when | Remedy |
| --- | --- | --- |
| `wan_degraded` | Gateway `wan_status` is not in `wan_ok_statuses` | `escalate` |
| `device_band_stuck` | A steer-eligible device is off the target band, at or below `poor_rssi_dbm`, **and** the target band exists on its AP | `band-steer` |
| `extender_flapping` | An extender is flapping/offline, or its backhaul is at or below `poor_backhaul_quality` | `reboot-extender` |
| `none` | Nothing fires | — |

Several faults can fire at once; `fault_precedence` config decides which the verdict
reports. The default order puts `device_band_stuck` ahead of `extender_flapping`
deliberately: **least disruptive remedy first**, since a band steer is invisible to the
customer while rebooting an extender drops it. That ordering is what makes the demo run
band-steer then reboot-extender.

Adding a fault type is a detector plus a name in `fault_precedence` — not a rewrite.
Every threshold is config (`app/modules/network/config.py` defaults, overridden per
tenant under `config_json.network`); there are no magic numbers at call sites.

### Verbs

`POST /gx/device-action {identifier, action, target, params}`:

| action | target | Effect |
| --- | --- | --- |
| `band-steer` | `device_id` | Moves a steer-eligible device to the target band; rssi recovers by `steer_rssi_gain_db`. |
| `reboot-extender` | `ap_id` | Extender drops and returns online; backhaul settles. |
| `reboot-ap` | `ap_id` | Any AP cycles; connected devices reattach. |

Each mutates state, so a follow-up `net-diagnostics` / `net-status` reflects it, and
`fault_cleared` is computed by re-reading committed state rather than assuming.

New verbs register a handler in `app/modules/network/actions.py` — no new gx route and
no new Genesys data action.

`params` is an optional **JSON object as a string** (`'{"band":"5"}'`), because a data
action contract cannot express a nested object. It is unused by the current verbs.

> **reboot-ap and the customer's own session:** rebooting the AP the customer is
> connected through would drop them. Offering to move them to mobile data and resuming
> afterwards is Genesys-side choreography (GX-D). The backend just flips the AP
> offline → online; client connectivity is not modelled here.

## Identifier normalization

`app/gx/normalize.py` turns whatever Genesys sends into `(value, id_type)`. It runs at
the gx boundary only.

| Genesys sends | Resolves to |
| --- | --- |
| `+447700900000` | `+447700900000` (phone) |
| `" 447700900000"` | `+447700900000` — an unencoded `+` decodes to a **space** |
| `447700900000` | `+447700900000` |
| `07700900000` | `+447700900000` — national, via the tenant's `country` |
| `+44 7700 900000` | `+447700900000` |
| `alice@example.net` | `alice@example.net` (email) |
| `NW000000` | `NW000000` (account_no) |
| `???` | unrecognized → `{found: false}`, never a 500 |

That second row is the load-bearing one: a literal `+` in a query string decodes to a
space, so `?identifier=+447700900000` silently searches for `" 447700900000"`. gx
recovers from it, but callers should still percent-encode (`%2B447700900000`); with
curl use `-G --data-urlencode "identifier=+447700900000"`.

A bare national number needs the tenant's `country` (pack config). With no country
configured it is unrecognized rather than guessed — there is no hardcoded default
country. Adding a country is a row in `COUNTRY_DIAL_RULES`, not a branch.

## Genesys data-action contracts

```bash
make contracts   # regenerates contracts/ from the live gx models
```

`contracts/` holds one importable Genesys **Web Services Data Action** per gx endpoint.
Schemas are derived from the Pydantic gx models, so a contract cannot drift from its
endpoint — and generation *refuses* to emit a non-scalar property, which makes "no
nested arrays" structural rather than a rule to remember. A test fails if the committed
files fall out of step with the code.

To import:

1. Add a **Web Services Data Actions** integration in Genesys Cloud.
2. Give it a **User Defined** credential containing `apiKey` = the API's `API_KEY`. The
   actions reference it as `${credentials.apiKey}`, so the key never travels through a
   flow.
3. Import `contracts/customer-context.json` and `contracts/verify-customer.json`.

They target `GX_BASE_URL` (default `https://backlot-api.krishharness.com`). The optional
`tenant` input maps to the `X-Tenant` header; leave it empty to use `DEFAULT_TENANT`.

## Deployment

Target is Unraid, containerized, behind a cloudflared tunnel. Postgres stays internal to
the compose network and is never published.

```bash
docker compose -f docker-compose.yml up -d
```

Use `-f docker-compose.yml` explicitly. `docker-compose.override.yml` is a
local-development file that Compose would otherwise auto-load, and it publishes the
Postgres port.

Set `POSTGRES_DATA_PATH=/mnt/user/appdata/backlot/postgres` in `.env` so the database
lands on a persistent Unraid share.

### cloudflared tunnel

The `cloudflared` service is behind a `tunnel` profile, so it stays out of the default
`docker compose up` and is inert without a token.

1. In Cloudflare Zero Trust → **Networks → Tunnels**, create a tunnel and copy its token.
2. Put it in `.env` as `CLOUDFLARE_TUNNEL_TOKEN=...`.
3. Add a public hostname on that tunnel:
   - **Subdomain** `api`, **Domain** `<your-domain>`
   - **Service** `HTTP://api:8000` — `api` is the compose service name, resolved over the
     compose network, which is why no port needs publishing to the host.
4. Start it:

   ```bash
   docker compose --profile tunnel up -d
   ```

`https://api.<your-domain>/health` should then answer, and that is the base URL a Genesys
data action points at. Keep `API_KEY` strong once the tunnel is public: the hostname is
reachable from the internet and the key is the only thing in front of it. The same goes
for `ADMIN_PASSWORD` — `/admin/*` rides the same public hostname, and it can restage or
reset a live demo.

## Layout

```
app/
  main.py  config.py  db.py  logging.py
  auth/       api-key middleware
  core/       Tenant + Customer Spine (models, tenancy, hashing, /v1 routes)
  modules/
    profile/  subscriber rollup + /v1/profile
    network/  WiFi engine: models, config, fault detectors, action verbs, /v1/network
  gx/         flat contract-safe endpoints, normalization, masking, contract exporter
  scenarios/  engine + packs/<tenant>/*.yaml + event log
  admin/      Basic auth, scenario controls, Jinja + htmx UI (htmx vendored)
  seed/       deterministic generator + network seeder + packs/<tenant>/pack.yaml
alembic/      migrations
contracts/    exported Genesys data actions (generated: make contracts)
scripts/      demo_be0.sh, demo_be1.sh, demo_be2.sh, demo_be3.sh
tests/
phases/       BE-*.md build briefs
```
