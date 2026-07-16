# BE-0 — Foundations

**Goal.** A running, containerized FastAPI skeleton with API-key auth, the Tenant + Customer Spine data model, migrations, and a deterministic seed framework. This is the floor every other phase stands on. No domain modules yet.

**Do not** build the network module, scenarios, admin UI, OIDC, or any `/gx/<module>-action` verbs here. Those are later phases.

## Prerequisites

- Docker + Docker Compose available.
- A Cloudflare account and a tunnel token for the public hostnames (can be added at the end; local build does not depend on it).
- Read `../CLAUDE.md`.

## Scope (in)

1. **Repo scaffold**: `pyproject.toml` (deps: fastapi, uvicorn, sqlalchemy>=2, alembic, pydantic>=2, pydantic-settings, psycopg[binary], faker; dev: pytest, httpx, ruff, mypy). `Makefile`, `.env.example`, `.gitignore`, `README.md`.
2. **App skeleton**: `app/main.py` (FastAPI app, `/health` returning `{status, tenant_default, version}`), `app/config.py` (pydantic-settings: `DATABASE_URL`, `API_KEY`, `DEFAULT_TENANT`, `APP_ENV`), `app/db.py` (SQLAlchemy 2.0 engine + session), `app/logging.py` (structured logs).
3. **Auth middleware**: reject any request without a valid `X-API-Key` (except `/health` and `/docs` + `/openapi.json`) with 401.
4. **Tenant + Customer Spine models** + Alembic migration (see schema below).
5. **Tenant resolver**: dependency that reads `X-Tenant` header, defaults to `DEFAULT_TENANT`. Every data query is tenant-scoped.
6. **Seed framework**: `python -m app.seed --tenant northwind` using Faker with a fixed seed. BE-0 seeds one tenant row (Northwind Mobile) plus ~10 parties with identities and one verification factor each. (Rich Telco device data is BE-2.) Seed must be idempotent and re-runnable.
7. **`v1` read endpoints** (internal, not gx yet): `GET /v1/tenants`, `GET /v1/parties?identifier=` to prove resolution works.
8. **Compose stack**: `api`, `db` (Postgres 16, data on a named volume mapped to an Unraid share path via `.env`), and a `cloudflared` service (token from `.env`, documented, may be inert locally).
9. **Tests**: health; api-key enforced (401/200); seed creates the expected counts; tenant scoping isolates parties; `/v1/parties?identifier=` resolves a seeded subscriber.
10. **`scripts/demo_be0.sh`**: curl walkthrough (health, unauthorized, authorized, list tenants, resolve a party).

## Schema (BE-0)

```
tenant        (tenant_id PK, slug UNIQUE, display_name, industry, branding_json, created_at)
party         (party_id PK, tenant_id FK, party_type[person|org], display_name, tier, created_at)
identity      (identity_id PK, party_id FK, id_type[phone|email|account_no|msisdn], value, is_primary,
               UNIQUE(tenant_id, id_type, value))
verification  (party_id FK, factor_type[dob|zip|pin|last4], value_hash)
contact_point (party_id FK, channel, value, consent)
```

Notes: `identity.value` is the resolution key for a Genesys ANI/email/account lookup. Uniqueness is per tenant. Hash verification factors; never store plaintext secrets.

## Config-over-code checkpoints for this phase

- Tenant identity (name, industry, branding) is a **seed/pack value**, not hardcoded.
- Seed volumes and the default tenant are **config**, not literals in code.
- No industry-specific logic anywhere in BE-0. It is entirely generic.

## Acceptance gate (all must pass)

- [ ] `docker compose up` brings up `api` + `db`; `api` becomes healthy.
- [ ] `GET /health` returns 200 with the default tenant.
- [ ] `/docs` renders; `/openapi.json` present.
- [ ] Request without `X-API-Key` to a `/v1` route returns 401; with the correct key returns 200.
- [ ] `make seed` (wrapping `python -m app.seed --tenant northwind`) creates 1 tenant + ~10 parties; re-running does not duplicate.
- [ ] `GET /v1/parties?identifier=<seeded phone>` resolves the right party; a foreign-tenant lookup does not leak it.
- [ ] `pytest` green; `ruff check` clean; `mypy app` clean.
- [ ] `scripts/demo_be0.sh` runs clean end to end.
- [ ] `README.md` documents: local run, `make seed`, env vars, and the cloudflared tunnel setup (how to point `api.<domain>` at the `api` service).

## Curl walkthrough (what `demo_be0.sh` should cover)

```bash
BASE=http://localhost:8000
curl -s $BASE/health
curl -s -o /dev/null -w "%{http_code}\n" $BASE/v1/tenants                     # expect 401
curl -s -H "X-API-Key: $API_KEY" $BASE/v1/tenants                             # expect northwind
curl -s -H "X-API-Key: $API_KEY" "$BASE/v1/parties?identifier=$SEED_PHONE"    # expect one party
```

## Session end

Update Notion `02 Backend build` BE-0 Status, append any decision to `01`, and if anything blocked you, log it to `06`. If the Notion MCP is not wired into Claude Code, print a `## Notion update` block for the human to paste.

## Definition of done

The gate passes and Krish signs off. Then request the BE-1 brief.
