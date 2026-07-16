# Backlot — Build index

Backend harness for Genesys Cloud demos. Read `CLAUDE.md` first (conventions, gate, memory protocol). Build one phase at a time from `phases/`. Status lives in Notion `02 Backend build`.

## Milestone M1: Telco WiFi self-healing (inbound), end to end

| Phase | Brief | Goal |
| --- | --- | --- |
| BE-0 | `phases/BE-0.md` | Scaffold, Compose + cloudflared, API-key auth, Tenant + Customer Spine, seed framework |
| BE-1 | `phases/BE-1.md` | Profile + gx flat-contract endpoints + verify-customer + exported contracts |
| BE-2 | `phases/BE-2.md` | Network & Devices module (WiFi engine) + Northwind Telco seed |
| BE-3 | `phases/BE-3.md` | Scenario engine + thin admin UI |
| BE-4 | `phases/BE-4.md` | Events / webhooks (telemetry emitter, CSAT write-back) |

## Later

| Phase | Goal |
| --- | --- |
| BE-5 | Banking + Insurance packs (loan, payments, billing, cases, bookings) + mock OIDC provider |
| BE-6 | Portability + polish (AWS-ready notes, README, per-demo scripts) |

Only `BE-0.md` is written in full right now. Each subsequent brief is generated when its predecessor passes its gate, so it can reflect what actually got built.

## Gate (every phase)

`pytest` green + ruff/mypy clean, `scripts/demo_<phase>.sh` clean, `/docs` updated, Krish sign-off.
