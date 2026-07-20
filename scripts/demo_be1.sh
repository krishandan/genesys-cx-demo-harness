#!/usr/bin/env bash
# BE-1 walkthrough: the gx surface Genesys binds to.
# Resolves a seeded Northwind subscriber via /gx/customer-context and verifies a factor.
#
#   ./scripts/demo_be1.sh
#
# Expects the stack up (make up) and seeded (make seed).
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
API_KEY="${API_KEY:-dev-local-key-change-me}"
SEED_PHONE="${SEED_PHONE:-+447700900000}"
SEED_PIN="${SEED_PIN:-24680}"  # 5 digits since BE-5

pass=0
fail=0

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show() { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }

# Reads one scalar out of a flat gx response.
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

gx_get() {
  curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=$1" \
    "$BASE/gx/customer-context"
}

assert_flat() {
  python3 -c "
import sys, json
body = json.load(sys.stdin)
nested = [k for k, v in body.items() if isinstance(v, (list, dict))]
sys.exit(1 if nested else 0)
" <<<"$1"
}

printf '\033[1mBacklot BE-1 — gx surface — %s\033[0m\n' "$BASE"

# ── 1. resolve ───────────────────────────────────────────────────────────────
step "GET /gx/customer-context?identifier=$SEED_PHONE — resolve a subscriber"
ctx=$(gx_get "$SEED_PHONE")
show "$ctx"
[[ $(jget found "$ctx") == "True" ]] && ok "found the subscriber" || bad "not found"
assert_flat "$ctx" && ok "response is flat (no nested arrays)" || bad "response has nested values"
[[ $(jget verified "$ctx") == "False" ]] && ok "verified is false at context stage" || bad "verified should be false"

party_id=$(jget party_id "$ctx")
display_name=$(jget display_name "$ctx")

# ── 2. the identifier Genesys actually sends ─────────────────────────────────
step "The same subscriber, spelled the ways Genesys sends it"
for variant in "+447700900000" " 447700900000" "07700900000" "447700900000"; do
  got=$(gx_get "$variant")
  if [[ $(jget party_id "$got") == "$party_id" ]]; then
    ok "'$variant' → same party"
  else
    bad "'$variant' did not resolve to $party_id"
  fi
done

# ── 3. not found ─────────────────────────────────────────────────────────────
step "GET /gx/customer-context — unknown number returns found:false, not an error"
missing=$(curl -sS -o /dev/null -w '%{http_code}' -G -H "X-API-Key: $API_KEY" \
  --data-urlencode "identifier=+447700900999" "$BASE/gx/customer-context")
[[ "$missing" == "200" ]] && ok "unknown identifier is HTTP 200" || bad "expected 200, got $missing"
missing_body=$(gx_get "+447700900999")
show "$missing_body"
[[ $(jget found "$missing_body") == "False" ]] && ok "found:false" || bad "expected found:false"

# ── 4. auth ──────────────────────────────────────────────────────────────────
step "gx without X-API-Key — expect 401"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/gx/customer-context?identifier=x")
[[ "$code" == "401" ]] && ok "unauthenticated gx call rejected (HTTP 401)" || bad "expected 401, got $code"

# ── 5. verify ────────────────────────────────────────────────────────────────
step "POST /gx/verify-customer — correct factor"
verified=$(curl -sS -X POST "$BASE/gx/verify-customer" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$SEED_PHONE\",\"factor_type\":\"pin\",\"factor_value\":\"$SEED_PIN\"}")
show "$verified"
[[ $(jget verified "$verified") == "True" ]] && ok "verified" || bad "should have verified"
assert_flat "$verified" && ok "response is flat" || bad "response has nested values"
masked=$(jget masked_name "$verified")
if [[ -n "$masked" && "$masked" != "$display_name" ]]; then
  ok "masked_name '$masked' hides '$display_name'"
else
  bad "masked_name did not mask the display name"
fi

step "POST /gx/verify-customer — wrong factor leaks nothing"
wrong=$(curl -sS -X POST "$BASE/gx/verify-customer" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$SEED_PHONE\",\"factor_type\":\"pin\",\"factor_value\":\"0000\"}")
show "$wrong"
[[ $(jget verified "$wrong") == "False" ]] && ok "verified:false" || bad "expected verified:false"
[[ -z $(jget party_id "$wrong") ]] && ok "no party_id leaked on failure" || bad "leaked a party_id"

# ── 6. contracts ─────────────────────────────────────────────────────────────
step "Exported data-action contracts"
for f in contracts/customer-context.json contracts/verify-customer.json; do
  if [[ -f "$f" ]] && python3 -c "import json,sys; json.load(open('$f'))" 2>/dev/null; then
    ok "$f is present and valid JSON"
  else
    bad "$f missing or invalid"
  fi
done

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
