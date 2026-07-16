#!/usr/bin/env bash
# BE-0 walkthrough: health, auth enforcement, tenant resolution, party resolution.
#
#   ./scripts/demo_be0.sh
#
# Expects the stack to be up (make up) and seeded (make seed).
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"

# Config, not literals: read the key and tenant from .env like every other consumer.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
API_KEY="${API_KEY:-dev-local-key-change-me}"
SEED_PHONE="${SEED_PHONE:-+447700900000}"

pass=0
fail=0

step()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()    { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()   { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show()  { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }

expect_code() {
  local want="$1" got="$2" what="$3"
  if [[ "$got" == "$want" ]]; then ok "$what (HTTP $got)"; else bad "$what — wanted HTTP $want, got $got"; fi
}

printf '\033[1mBacklot BE-0 — %s\033[0m\n' "$BASE"

# ── 1. health ────────────────────────────────────────────────────────────────
step "GET /health — public, reports the default tenant"
health=$(curl -sS "$BASE/health")
show "$health"
[[ $(python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" <<<"$health") == "ok" ]] \
  && ok "status is ok" || bad "status is not ok"

# ── 2. auth is enforced ──────────────────────────────────────────────────────
step "GET /v1/tenants without X-API-Key — expect 401"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/v1/tenants")
expect_code 401 "$code" "unauthenticated request rejected"

step "GET /v1/tenants with a wrong X-API-Key — expect 401"
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "X-API-Key: wrong" "$BASE/v1/tenants")
expect_code 401 "$code" "bad key rejected"

# ── 3. authorized read + tenant resolution ───────────────────────────────────
step "GET /v1/tenants with the key — expect the northwind tenant"
tenants=$(curl -sS -H "X-API-Key: $API_KEY" "$BASE/v1/tenants")
show "$tenants"
grep -q '"slug": *"northwind"' <<<"$tenants" && ok "resolved northwind" || bad "northwind not resolved"

# ── 4. resolve a subscriber by identifier ────────────────────────────────────
# -G + --data-urlencode matters: a bare '+' in a query string decodes to a space,
# so an E.164 number must be percent-encoded. Genesys data actions must do the same.
step "GET /v1/parties?identifier=$SEED_PHONE — expect one party"
party=$(curl -sS -G -H "X-API-Key: $API_KEY" \
  --data-urlencode "identifier=$SEED_PHONE" "$BASE/v1/parties")
show "$party"
count=$(python3 -c "import sys,json;print(len(json.load(sys.stdin)))" <<<"$party")
[[ "$count" == "1" ]] && ok "resolved exactly one party" || bad "expected 1 party, got $count"

# ── 5. tenant scoping holds ──────────────────────────────────────────────────
step "Same phone under X-Tenant: acme — expect no leak"
foreign_code=$(curl -sS -o /dev/null -w '%{http_code}' -G \
  -H "X-API-Key: $API_KEY" -H "X-Tenant: acme" \
  --data-urlencode "identifier=$SEED_PHONE" "$BASE/v1/parties")
# acme is a test-only pack and is not seeded here, so an unknown tenant is a 404.
# Either way the northwind party must not come back.
if [[ "$foreign_code" == "404" ]]; then
  ok "foreign tenant 'acme' is unknown here (HTTP 404) — nothing leaked"
else
  foreign=$(curl -sS -G -H "X-API-Key: $API_KEY" -H "X-Tenant: acme" \
    --data-urlencode "identifier=$SEED_PHONE" "$BASE/v1/parties")
  [[ "$foreign" == "[]" ]] && ok "foreign-tenant lookup returned []" || bad "LEAK: $foreign"
fi

# ── summary ──────────────────────────────────────────────────────────────────
printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
