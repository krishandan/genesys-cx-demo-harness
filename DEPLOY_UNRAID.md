# DEPLOY-1 — Backlot on Unraid (always-on)

**Goal.** The full stack runs on Unraid behind the existing cloudflared tunnel, always-on, so Genesys binds to a stable origin instead of a laptop. **The gate is one sentence: `https://backlot-api.krishharness.com/health` returns 200 from the public internet with the Mac powered off, Northwind seeded.**

Split in two: Part A is a code artifact Claude Code produces in the `backlot` repo. Part B is manual Unraid work (Krish), guided interactively because the plugin UI shifts.

## Deploy shape (locked once this passes)
- **One unified compose** runs `api` (FastAPI :8000), `db` (Postgres 16), `web` (Next.js :3000), and `cloudflared` on a single Docker network.
- `web` reaches the backend internally at `http://api:8000` (`BACKLOT_BASE_URL`). cloudflared routes `backlot-api` → `api:8000` and `backlot-app` → `web:3000` with the **existing** token (no reissue).
- **Base compose only.** The dev `docker-compose.override.yml` (publishes 5432) is not used on Unraid; Postgres stays internal.
- Images **build on Unraid** from both repo directories (Compose Manager build), no registry.

## Postgres data
- `appdata` share set to **cache-only** (prefer cache): DB on SSD, mover never touches it.
- Bind-mount data to `PGDATA_PATH=/mnt/user/appdata/backlot/pgdata` (bind mount, not a named volume, for visibility and backup). Optionally use the direct pool path `/mnt/cache/appdata/backlot/pgdata` to bypass the FUSE layer.

---

## Part A — Claude Code (in the `backlot` repo)
Produce, and stop at the Part A gate:

1. **`deploy/docker-compose.unraid.yml`** — `api`, `db`, `web`, `cloudflared` on one network.
   - `api` builds from the backlot repo context; `web` builds from the sibling `backlot-web` repo (parameterize the context path, e.g. `../backlot-web`, and document the expected side-by-side layout).
   - `db` is Postgres 16 with data bind-mounted to `${PGDATA_PATH}`.
   - `cloudflared` runs `tunnel --no-autoupdate run --token ${CLOUDFLARE_TUNNEL_TOKEN}`.
   - `web` env: `BACKLOT_BASE_URL=http://api:8000`, `TENANT=northwind`. All secrets from `.env`.
2. **`deploy/.env.example`** — `CLOUDFLARE_TUNNEL_TOKEN`, `API_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD`, `PGDATA_PATH`, `POSTGRES_*`, `TENANT`, `DEFAULT_TENANT`.
3. **`deploy/README.md`** — the Part B steps below, including the seed and the public-health verification.

**Part A gate (local, under Colima — do NOT start the real cloudflared):**
- [ ] `docker compose -f deploy/docker-compose.unraid.yml config` validates.
- [ ] `api` and `web` images build.
- [ ] Bringing up the **subset** `api db web` (cloudflared excluded) → `web` reaches `api` at `http://api:8000`, `/health` 200 internally, the site renders.
- [ ] **Do not run the real `cloudflared` locally** — it would repoint the production hostnames at the Mac. Its correctness is verified on Unraid in Part B. Note this in the README.

## Part B — Manual on Unraid (Krish, interactive)
1. Set `appdata` share **cache-only**; create `/mnt/user/appdata/backlot/pgdata`.
2. Put **both repo dirs side by side** on the box (git clone or copy) so the compose build contexts resolve.
3. In **Compose Manager**, add a stack pointing at `deploy/docker-compose.unraid.yml`; set `.env` (token, `API_KEY`, admin creds, `PGDATA_PATH`).
4. Compose up (build). Then run migrate + seed once to populate Northwind.
5. Confirm the tunnel shows **Healthy** in Cloudflare and the routes point at the Unraid containers.
6. **Gate (the real test):** from **off your LAN** (phone on cellular), with the **Mac powered off**:
   - `https://backlot-api.krishharness.com/health` → 200.
   - `https://backlot-app.krishharness.com` → the Northwind site renders.
   - authenticated `GET /gx/net-diagnostics?identifier=%2B447700900000` → the seeded verdict.

## Definition of done
The public health check passes with the Mac off, Northwind seeded, tunnel Healthy. This unblocks all Genesys wiring (GX-A onward).
