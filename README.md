# Backlot

A reusable backend harness for Genesys Cloud demos. It exposes a stable set of APIs and
dummy customers so that demo work happens in the Genesys UI, not here.

New customers, industries, and scenarios are **data, not code**: a new telco is a new
seed pack, same code.

- **Tenant** = the Genesys customer (a telco, a bank, an insurer).
- **Subscriber / end customer** = that tenant's customer, the person who messages in.

Phase briefs live in `phases/`. This README covers **BE-0 — Foundations**: the app
skeleton, API-key auth, the Tenant + Customer Spine, migrations, and the seed framework.

## Requirements

- Docker + Docker Compose
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/) (only for host-run tests and linting)

## Local run

```bash
make up      # copies .env.example → .env, builds, starts api + db
make seed    # seeds the Northwind Mobile pack (idempotent)
make demo    # the BE-0 curl walkthrough
```

Then:

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
| `API_KEY` | `dev-local-key-change-me` | Required in `X-API-Key` on every `/v1` (later `/gx`) call. **Change this off local.** |
| `DEFAULT_TENANT` | `northwind` | Tenant used when a request sends no `X-Tenant` header. |
| `DATABASE_URL` | `postgresql+psycopg://backlot:backlot@db:5432/backlot` | SQLAlchemy URL. `db` is the compose service name. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `backlot` | Postgres credentials. |
| `POSTGRES_DATA_PATH` | `./.data/postgres` | Host path backing the `pgdata` volume. On Unraid: `/mnt/user/appdata/backlot/postgres`. |
| `API_PORT` | `8000` | Host port for the api service. |
| `POSTGRES_PORT` | `5432` | Host port for Postgres — local development only. |
| `LOG_LEVEL` | `INFO` | Structured JSON logs to stdout. |
| `CLOUDFLARE_TUNNEL_TOKEN` | *(empty)* | Tunnel token. Blank locally; the service is inert. |

## Auth

Every `/v1` route requires the `X-API-Key` header and returns 401 without it. `/health`,
`/docs`, and `/openapi.json` are public so container healthchecks and Genesys data-action
imports work unauthenticated.

Identity for M1 is **verify-then-context**: resolve the subscriber by identifier, then
carry identity as context. `/gx/verify-customer` arrives in BE-1; OIDC is deferred to BE-5.

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

BE-0 seeds one tenant plus 10 parties, each with three identities, one hashed
verification factor, and two contact points. Rich telco device data is BE-2.

### Adding a customer

Add `app/seed/packs/<slug>/pack.json` and run `python -m app.seed --tenant <slug>`. No
Python changes. The tenant's name, industry, and branding are pack values.

```jsonc
{
  "tenant": { "slug": "...", "display_name": "...", "industry": "...", "branding_json": {} },
  "seed": {
    "faker_seed": 20260716,          // fixed → deterministic
    "party_count": 10,
    "identities": ["phone", "email", "account_no"],
    "verification_factor": "dob",
    "phone_pattern": "+447700900{index:03d}"
  }
}
```

### Synthetic data only

Never real PII. Seeded phone numbers sit in the `+447700900xxx` range Ofcom reserves for
fiction, and emails use the reserved `example.net` domain, so no seeded identifier can
reach a real person. Verification factors are stored only as SHA-256 digests.

## API (BE-0)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | none | `{status, tenant_default, version}` |
| GET | `/v1/tenants` | `X-API-Key` | The tenant in scope for this request. |
| GET | `/v1/parties?identifier=` | `X-API-Key` | Resolve a subscriber by phone / email / account_no / msisdn. |

The flat, contract-safe `/gx/` surface that Genesys binds to is BE-1.

> **Encoding a phone number:** a literal `+` in a query string decodes to a space, so
> E.164 identifiers must be percent-encoded (`%2B447700900000`). With curl, use
> `-G --data-urlencode "identifier=+447700900000"`. Genesys data actions must do the same.

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
reachable from the internet and the key is the only thing in front of it.

## Layout

```
app/
  main.py  config.py  db.py  logging.py
  auth/       api-key middleware
  core/       Tenant + Customer Spine (models, tenancy, /v1 routes)
  seed/       deterministic generator + packs/<tenant>/pack.json
alembic/      migrations
scripts/      demo_be0.sh
tests/
phases/       BE-*.md build briefs
```
