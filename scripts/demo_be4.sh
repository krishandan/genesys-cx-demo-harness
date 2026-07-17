#!/usr/bin/env bash
# BE-4 walkthrough: events, CSAT write-back, and the telemetry seam.
#
#   ./scripts/demo_be4.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
API_KEY="${API_KEY:-dev-local-key-change-me}"
ADMIN="${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-backlot-admin-change-me}"
DEMO="${DEMO_PHONE:-+447700900000}"

pass=0
fail=0

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show() { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

gx()  { curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=$DEMO" "$BASE/gx/$1"; }
post() { curl -sS -X POST "$BASE/gx/$1" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "$2"; }
code() { curl -sS -o /dev/null -w '%{http_code}' "$@"; }

assert_flat() {
  python3 -c "
import sys, json
b = json.load(sys.stdin)
sys.exit(1 if [k for k, v in b.items() if isinstance(v, (list, dict))] else 0)
" <<<"$1"
}

printf '\033[1mBacklot BE-4 — events + CSAT + telemetry — %s\033[0m\n' "$BASE"

# Start from the baseline so the run is repeatable.
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null

# ── 1. last_channel is derived before any event ──────────────────────────────
step "GET /gx/customer-context — last_channel derived from the spine (no events yet)"
ctx=$(gx customer-context)
before=$(jget last_channel "$ctx")
[[ -n "$before" ]] && ok "last_channel derived: '$before'" || bad "last_channel empty"

# ── 2. record an interaction, last_channel now comes from it ─────────────────
step "POST /gx/interaction-event — record a webmessaging interaction"
ie=$(post interaction-event '{"identifier":"'"$DEMO"'","channel":"webmessaging","kind":"inbound"}')
show "$ie"
[[ $(jget ok "$ie") == "True" ]] && ok "interaction stored" || bad "interaction failed"

after=$(jget last_channel "$(gx customer-context)")
[[ "$after" == "webmessaging" ]] && ok "last_channel now sourced from the event: '$after'" \
  || bad "expected webmessaging, got '$after'"
[[ "$before" != "$after" ]] && ok "derived → event-sourced transition confirmed" || bad "no transition"

# ── 3. CSAT write-back ───────────────────────────────────────────────────────
step "POST /gx/csat — write back a score"
cs=$(post csat '{"identifier":"'"$DEMO"'","score":5,"comment":"fixed my wifi","conversation_ref":"abc123"}')
show "$cs"
[[ $(jget ok "$cs") == "True" ]] && ok "CSAT stored" || bad "CSAT failed"
assert_flat "$cs" && ok "response is flat" || bad "response has nested values"

step "POST /gx/csat — a bad score is a flat 4xx"
c=$(code -X POST "$BASE/gx/csat" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"identifier":"'"$DEMO"'","score":9}')
[[ "$c" == "400" ]] && ok "score 9 rejected (HTTP $c)" || bad "expected 400, got $c"

# ── 4. telemetry seam ────────────────────────────────────────────────────────
step "GET /gx/telemetry — empty at baseline (a proactive poll finds nothing)"
t0=$(gx telemetry)
[[ "$t0" == "[]" ]] && ok "no telemetry yet" || bad "expected [], got $t0"

step "Stage the fault (admin: apply wifi_degraded) — the network module emits telemetry"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" \
  -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}' >/dev/null && ok "staged"

step "GET /gx/telemetry — the emitted network.degraded event, a top-level flat array"
tel=$(gx telemetry)
show "$tel"
count=$(python3 -c "import sys,json;print(len(json.load(sys.stdin)))" <<<"$tel")
[[ "$count" -ge 1 ]] && ok "$count telemetry event(s)" || bad "expected >=1"
kind=$(python3 -c "import sys,json;print(json.load(sys.stdin)[0]['kind'])" <<<"$tel")
[[ "$kind" == "network.degraded" ]] && ok "kind: network.degraded" || bad "unexpected kind $kind"
python3 -c "
import sys, json
for e in json.load(sys.stdin):
    assert not [k for k,v in e.items() if isinstance(v,(list,dict))], 'nested value in telemetry item'
" <<<"$tel" && ok "every feed item is flat" || bad "a feed item is nested"

# ── 5. a new event kind is data, not a migration ─────────────────────────────
step "A new event kind needs no migration (kind + JSONB payload)"
# Records via interaction-event with a novel channel; the store takes any kind/payload.
post interaction-event '{"identifier":"'"$DEMO"'","channel":"whatsapp","kind":"inbound"}' >/dev/null
newchan=$(jget last_channel "$(gx customer-context)")
[[ "$newchan" == "whatsapp" ]] && ok "arbitrary channel 'whatsapp' stored and surfaced" \
  || bad "expected whatsapp, got '$newchan'"

# ── 6. admin activity feed ───────────────────────────────────────────────────
# Record a fresh CSAT here: the wifi_degraded apply above ran reset_first, which
# clears the event store, so the earlier CSAT is gone. That is the demo-reset
# semantic — each take starts clean.
post csat '{"identifier":"'"$DEMO"'","score":5,"comment":"all sorted","conversation_ref":"conv-42"}' >/dev/null

step "GET /admin/activity — interactions, CSAT and telemetry in one feed (admin auth)"
act=$(curl -sS -u "$ADMIN" "$BASE/admin/activity")
kinds=$(python3 -c "import sys,json;print(' '.join(sorted({a['kind'] for a in json.load(sys.stdin)})))" <<<"$act")
ok "activity kinds: $kinds"
for want in interaction csat network.degraded; do
  grep -q "\"$want\"" <<<"$act" && ok "$want present in the feed" || bad "$want missing"
done
c=$(code -H "X-API-Key: $API_KEY" "$BASE/admin/activity")
[[ "$c" == "401" ]] && ok "the gx key does NOT open /admin/activity (HTTP $c)" || bad "expected 401, got $c"

# ── 7. leave it clean ────────────────────────────────────────────────────────
step "Reset to baseline"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null
[[ $(jget fault_type "$(gx net-diagnostics)") == "none" ]] && ok "baseline restored" || bad "not restored"

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
