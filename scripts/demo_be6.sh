#!/usr/bin/env bash
# BE-6 walkthrough: coverage is a durable signal, separate from faults.
#
# Shows the thing the agent must be able to state as a fact: after every fault is fixed
# (fault_type -> none), the home STILL has a structural coverage weakness (a cluster of
# devices at the edge of the Upstairs Extender's range), so the mesh upsell is grounded
# rather than a mid-problem sales pitch. Coverage does not flip to good when the fault
# clears, and /gx/offers keys off the exact same signal /gx/net-status reports.
#
#   ./scripts/demo_be6.sh
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
HEALTHY="+447700900001"

pass=0
fail=0
step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

gx()  { curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=${2:-$DEMO}" "$BASE/gx/$1"; }
post() { curl -sS -X POST "$BASE/gx/$1" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "$2"; }
steer() { post device-action "{\"identifier\":\"$DEMO\",\"action\":\"$1\",\"target\":\"$2\",\"params\":\"\"}"; }

# Reads net-status coverage + offers eligibility and prints a durability line.
readout() {
  local label="$1" st offer fault cov cnt area elig
  st=$(gx net-status)
  offer=$(gx offers)
  fault=$(jget fault_type "$st"); cov=$(jget coverage "$st")
  cnt=$(jget coverage_device_count "$st"); area=$(jget coverage_worst_area "$st")
  elig=$(jget eligible "$offer")
  printf '  %-22s fault=%-18s coverage=%-4s (%s on %s)  offer_eligible=%s\n' \
    "$label" "$fault" "$cov" "$cnt" "$area" "$elig"
  [[ "$cov" == "weak" && "$elig" == "True" ]] && ok "$label: coverage weak & offer stands" \
    || bad "$label: expected weak+eligible, got coverage=$cov eligible=$elig"
}

printf '\033[1mBacklot BE-6 — coverage is durable, separate from faults — %s\033[0m\n' "$BASE"

step "Reset to a clean, healthy baseline"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null
st=$(gx net-status)
[[ $(jget healthy "$st") == "True" ]] && ok "network healthy (fault_type none)" || bad "not healthy at baseline"
[[ $(jget coverage "$st") == "weak" ]] \
  && ok "yet coverage is WEAK — the two ideas are separate" || bad "coverage should be weak at baseline"
printf '  coverage_note: "%s"\n' "$(jget coverage_note "$st")"

step "The agent states the coverage gap as a fact (net-status), and the offer echoes it"
note=$(jget coverage_note "$(gx net-status)")
reason=$(jget reason "$(gx offers)")
[[ -n "$note" && "$note" == "$reason" ]] \
  && ok "offer.reason == net-status.coverage_note (single source of truth)" \
  || bad "offer reason and coverage note disagree"

step "A healthy home with no cluster reads coverage good, and is NOT offer-eligible"
hs=$(gx net-status "$HEALTHY")
[[ $(jget coverage "$hs") == "good" && $(jget coverage_device_count "$hs") == "0" ]] \
  && ok "$HEALTHY: coverage good, 0 devices at the edge" || bad "$HEALTHY should read good"
[[ $(jget eligible "$(gx offers "$HEALTHY")") == "False" ]] \
  && ok "$HEALTHY: not offer-eligible (clean contrast)" || bad "$HEALTHY should not be eligible"

step "Now run the full self-heal — coverage must stay weak the whole way"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" \
  -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}' >/dev/null
readout "staged wifi_degraded"

TGT=$(jget primary_target "$(gx net-diagnostics)")
steer band-steer "$TGT" >/dev/null
readout "after band-steer"

EXT=$(jget primary_target "$(gx net-diagnostics)")
steer reboot-extender "$EXT" >/dev/null
readout "after reboot-extender"

step "Every fault is now fixed — but coverage is still weak (the whole point)"
final=$(gx net-status)
[[ $(jget fault_type "$final") == "none" ]] && ok "fault_type reached none" || bad "a fault remains"
[[ $(jget healthy "$final") == "True" ]] && ok "healthy is true" || bad "not healthy"
[[ $(jget coverage "$final") == "weak" ]] \
  && ok "coverage STILL weak after the reboot — a reboot doesn't move devices closer" \
  || bad "coverage flipped to good after the fix"
[[ $(jget eligible "$(gx offers)") == "True" ]] \
  && ok "the mesh offer still stands — grounded, not a mid-problem pitch" || bad "offer vanished"

curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
