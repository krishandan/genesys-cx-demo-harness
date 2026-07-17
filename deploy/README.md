# Backlot on Unraid — always-on deploy

The full stack runs on Unraid behind the existing Cloudflare tunnel, so Genesys binds to
a stable origin instead of a laptop.

**The gate is one sentence:** `https://backlot-api.krishharness.com/health` returns 200
from the public internet with the Mac powered off, Northwind seeded.

One unified compose runs four services on one Docker network:

| Service | Image / build | Port | Reached by |
| --- | --- | --- | --- |
| `api` | build from `backlot` repo | 8000 | cloudflared → `http://api:8000` |
| `web` | build from `backlot-web` repo | 3000 | cloudflared → `http://web:3000` |
| `db` | `postgres:16` | 5432 | `api` only, internal |
| `cloudflared` | `cloudflare/cloudflared` | — | the internet |

No host ports are published. Postgres stays internal; `api` and `web` are reached only
through the tunnel. `web` talks to the backend internally at `http://api:8000`.

## Side-by-side repos (build contexts)

This compose builds both images on the box, no registry. Compose resolves relative build
contexts **from this file's directory** (`backlot/deploy/`), so the two repos must sit
side by side:

```
<parent>/
  backlot/        ← api build context is ..            (this repo)
    deploy/docker-compose.unraid.yml
  backlot-web/    ← web build context is ../../backlot-web
```

Override `API_CONTEXT` / `WEB_CONTEXT` in `.env` only if your layout differs.

---

## Part A — verify locally (done in the `backlot` repo)

> **Never start the real `cloudflared` locally.** With a real token it would repoint the
> production hostnames (`backlot-api` / `backlot-app`) at your machine. Bring up only the
> `api db web` subset, and keep `CLOUDFLARE_TUNNEL_TOKEN` empty in a local `deploy/.env`.
> cloudflared's correctness is verified on Unraid in Part B, not here.

```bash
cd backlot
cp deploy/.env.example deploy/.env       # keep CLOUDFLARE_TUNNEL_TOKEN empty; set a local PGDATA_PATH

# 1. the compose validates
docker compose -f deploy/docker-compose.unraid.yml config

# 2. the images build
docker compose -f deploy/docker-compose.unraid.yml build api web

# 3. bring up the SUBSET only (cloudflared excluded — name the services)
docker compose -f deploy/docker-compose.unraid.yml up -d --build api db web

# 4. web reaches api over the compose network, /health is 200, the site renders
docker compose -f deploy/docker-compose.unraid.yml exec web wget -qO- http://api:8000/health
docker compose -f deploy/docker-compose.unraid.yml exec api \
  python -c "import urllib.request as u; print(u.urlopen('http://web:3000').status)"

docker compose -f deploy/docker-compose.unraid.yml down
```

Running the BE-4 dev stack at the same time? It shares the project name `backlot`. Add
`-p backlot_deploy` to every command above to keep the two isolated.

---

## Part B — deploy on Unraid (manual, interactive)

### 1. Storage
- Set the **`appdata` share to cache-only** (prefer cache): the DB lives on SSD and the
  mover never touches it.
- Create the Postgres data directory:
  ```bash
  mkdir -p /mnt/user/appdata/backlot/pgdata
  ```
  Optionally use the direct pool path `/mnt/cache/appdata/backlot/pgdata` to bypass the
  FUSE layer.

### 2. Get both repos on the box, side by side
`git clone` (or copy) `backlot` and `backlot-web` into the same parent directory so the
build contexts resolve (see [Side-by-side repos](#side-by-side-repos-build-contexts)).

### 3. Configure `.env`
```bash
cp backlot/deploy/.env.example backlot/deploy/.env
```
Set:
- `CLOUDFLARE_TUNNEL_TOKEN` — the **existing** backlot tunnel token (no reissue).
- `API_KEY` — strong; this is what Genesys sends and what `web` uses internally.
- `ADMIN_USER` / `ADMIN_PASSWORD` — strong; the admin UI is on the public hostname.
- `POSTGRES_PASSWORD` — strong.
- `PGDATA_PATH=/mnt/user/appdata/backlot/pgdata`.

### 4. Bring the stack up (Compose Manager)
In **Compose Manager**, add a stack pointing at `backlot/deploy/docker-compose.unraid.yml`
with that `.env`, then compose up (build). This starts all four services, always-on.
`api` runs `alembic upgrade head` on start, so migrations apply automatically.

### 5. Seed Northwind (one-shot, once)
```bash
docker compose -f deploy/docker-compose.unraid.yml exec api python -m app.seed --tenant northwind
```
Expect `parties: 10`, plus the network topology counts.

### 6. Confirm the tunnel
In the Cloudflare Zero Trust dashboard the tunnel should read **Healthy**, with public
hostname routes:
- `backlot-api.krishharness.com` → `http://api:8000`
- `backlot-app.krishharness.com` → `http://web:3000`

### 7. The gate — the real test
From **off your LAN** (phone on cellular), with the **Mac powered off**:
```bash
curl https://backlot-api.krishharness.com/health
#   → {"status":"ok","tenant_default":"northwind",...}

curl "https://backlot-api.krishharness.com/gx/net-diagnostics?identifier=%2B447700900000" \
  -H "X-API-Key: <API_KEY>"
#   → the seeded verdict (fault_type none at the healthy baseline; stage wifi_degraded
#     via /admin to see device_band_stuck)
```
And `https://backlot-app.krishharness.com` renders the Northwind site.

> The admin UI (stage/reset demo scenarios) lives on the **api** host, behind HTTP Basic:
> `https://backlot-api.krishharness.com/admin/` (`ADMIN_USER` / `ADMIN_PASSWORD`). It is a
> separate trust domain from the gx `API_KEY`.

## Definition of done
Public health check passes with the Mac off, Northwind seeded, tunnel Healthy. This
unblocks all Genesys wiring (GX-A onward).

## Operations

```bash
# logs
docker compose -f deploy/docker-compose.unraid.yml logs -f api

# re-seed / reset a demo (admin)  — see the backlot README "Scenarios" section
docker compose -f deploy/docker-compose.unraid.yml exec api python -m app.seed --tenant northwind

# back up Postgres (data is a bind mount at PGDATA_PATH)
docker compose -f deploy/docker-compose.unraid.yml exec db \
  pg_dump -U backlot backlot > backlot-$(date +%Y%m%d).sql
```

Postgres data is a **bind mount** at `PGDATA_PATH`, so it survives `compose down` and is
visible on the share for backup.
