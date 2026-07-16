# CLAUDE.md — backlot

You are building **Backlot**, a reusable backend harness for Genesys Cloud demos. Read this file fully before doing anything.

## What Backlot is

A modular monolith (FastAPI + Postgres) that exposes a stable set of APIs and dummy customers so that demo work happens in the Genesys UI, not here. New customers, industries, and scenarios are **data, not code**.

- **Tenant** = the Genesys customer (a telco, a bank, an insurer).
- **Subscriber / end customer** = that tenant's customer, the person who "messages in". This is the dummy customer a Genesys flow resolves by identifier (phone / email / account).
- Everything is **tenant-scoped**. A new telco is a new pack, same code.

## The rule that governs every design choice: config-over-code

Before adding a route, a model field, or a branch, ask: can this be a seed value, a pack config entry, or a scenario file instead? New customers, new data, and new demo situations must be expressible as **files**, not code. You only write Python for a genuinely new capability (a new verb like band-steer), and once written it is reusable across every future demo.

## Stack (do not substitute without a decision-log entry)

Python 3.12, FastAPI, Postgres 16, SQLAlchemy 2.0 (sync), Alembic, Pydantic v2. Tooling: ruff, mypy, pytest. Containerized with Docker Compose. Deployed on Unraid behind a cloudflared tunnel; keep everything 12-factor (env config, no host assumptions) so the same image runs on the M2 Pro or AWS later.

## gx surface (hybrid, this is load-bearing)

Genesys binds to endpoints under `/gx/`. These return **flat, contract-safe JSON: no nested arrays** (Genesys data action output contracts cannot express them). An array of flat objects as the top-level response is fine; an array nested inside an object property is not.

- Concrete **resource endpoints** for stable nouns: `/gx/customer-context`, `/gx/cases`, `/gx/bookings`, `/gx/net-diagnostics`.
- One **action endpoint per module** for verbs: `POST /gx/<module>-action {action, target, params}`. New verbs register a handler; they rarely need a new route or a new Genesys data action.
- The rich internal API lives under `/v1/`; `/gx/` wraps and flattens it.
- Export each data action's input/output contract JSON to `contracts/` so it imports straight into Genesys.

## Auth

`X-API-Key` header on every gx and v1 call, validated in middleware. For M1 (the WiFi demo) identity is **verify-then-context**: resolve the subscriber by identifier, optionally confirm a factor via `/gx/verify-customer`, then carry identity as context. The mock OIDC provider is deferred to BE-5 (Banking). Do not build OIDC now.

## Repo layout (target)

```
backlot/
  docker-compose.yml  Dockerfile  Makefile  pyproject.toml  .env.example
  alembic/
  app/
    main.py  config.py  db.py  logging.py
    auth/            # api-key middleware, verify-customer
    core/            # Tenant + Customer Spine (party / identity / verification)
    modules/         # profile, network, cases, bookings, billing, loan
    gx/              # flat contract-safe endpoints + contract exporter
    scenarios/       # engine + packs/<tenant>/*.yaml
    events/          # webhooks, telemetry emitter, write-back
    admin/           # thin Jinja + htmx UI
    seed/            # deterministic faker generators + packs/<tenant>/
  contracts/         # exported Genesys data action JSON
  scripts/           # demo_<phase>.sh curl walkthroughs
  tests/
  phases/            # BE-*.md build briefs (read the active one)
```

## Phase gate (do not advance without all four)

1. `pytest` green, ruff clean, mypy clean.
2. `scripts/demo_<phase>.sh` runs a clean curl walkthrough.
3. OpenAPI at `/docs` reflects the new surface.
4. Krish signs off.

Work strictly one phase at a time. The active brief is in `phases/`. Do not scaffold future phases early.

## Memory protocol (Notion) — run this every session

The shared memory lives in Notion under the hub **Backlot · Genesys Demo Harness**.

- Hub: https://app.notion.com/p/39f9eb98391d81a08c01d8e56933ae4f
- 01 Decisions log: `39f9eb98-391d-81e6-a96a-c8d7ed3cb1ff`
- 02 Backend build: `39f9eb98-391d-818e-8968-d0182dca21f7`
- 06 Issues & blockers: `39f9eb98-391d-8110-b2f5-eb71ab7dc1a9`
- 07 API registry: `39f9eb98-391d-8126-8eff-ff398006b077`

**At session start:** read the hub, `01 Decisions log`, `02 Backend build`, and `06 Issues & blockers`. Honor locked decisions.

**At session end:** update the phase Status on `02`, append any new endpoint to `07`, append any new decision to `01`, and log any blocker to `06` (what was tried, exact error, hypothesis, what is needed).

**If the Notion MCP is not configured in this Claude Code environment:** do not fail. Instead, end every session by printing a `## Notion update` block in markdown (phase status, new endpoints, decisions, blockers) for the human to paste into the pages above.

## Non-negotiables

- Synthetic data only. Never real PII. No PCI in secure flows.
- Keep gx responses flat (no nested arrays) and fast.
- Tenant-scope every query.
- Prefer a pack/scenario file over new code.
