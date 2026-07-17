#!/usr/bin/env bash
# BE-3 walkthrough: the scenario engine + admin auth boundary.
#
# The point of this phase: run the WiFi demo repeatedly with apply/reset alone —
# no `make seed` anywhere below.
#
#   ./scripts/demo_be3.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
TAKES="${TAKES:-2}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
API_KEY="${API_KEY:-dev-local-key-change-me}"
ADMIN="${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-backlot-admin-change-me}"
DEMO_PHONE="${DEMO_PHONE:-+447700900000}"

pass=0
fail=0

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show() { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

admin_post() { curl -sS -u "$ADMIN" -X POST "$BASE$1" "${@:2}"; }
gx() { curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=$DEMO_PHONE" "$BASE/gx/$1"; }
device_action() {
  curl -sS -X POST "$BASE/gx/device-action" -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"$1\",\"target\":\"$2\"}"
}
code() { curl -sS -o /dev/null -w '%{http_code}' "$@"; }

printf '\033[1mBacklot BE-3 — scenario engine + admin — %s\033[0m\n' "$BASE"

# ── 1. auth boundary ─────────────────────────────────────────────────────────
step "Admin and gx are separate trust domains"
c=$(code -X POST -H "X-API-Key: $API_KEY" "$BASE/admin/scenario/reset")
[[ "$c" == "401" ]] && ok "the Genesys X-API-Key does NOT open /admin (HTTP $c)" \
  || bad "the gx key opened /admin (HTTP $c)"
c=$(code -u "$ADMIN" "$BASE/gx/net-status?identifier=%2B447700900000")
[[ "$c" == "401" ]] && ok "the admin credential does NOT open /gx (HTTP $c)" \
  || bad "admin creds opened /gx (HTTP $c)"
c=$(code "$BASE/admin/")
[[ "$c" == "401" ]] && ok "/admin needs credentials (HTTP $c)" || bad "expected 401, got $c"
c=$(code -u "$ADMIN" "$BASE/admin/")
[[ "$c" == "200" ]] && ok "admin UI opens with the admin credential (HTTP $c)" || bad "expected 200, got $c"

# ── 2. scenarios are files ───────────────────────────────────────────────────
step "GET /admin/scenarios — packs, not code"
scenarios=$(curl -sS -u "$ADMIN" "$BASE/admin/scenarios")
names=$(python3 -c "import sys,json;print(' '.join(s['name'] for s in json.load(sys.stdin)))" <<<"$scenarios")
ok "available: $names"
for want in wifi_degraded outage_in_area healthy; do
  grep -q "\"$want\"" <<<"$scenarios" && ok "$want present" || bad "$want missing"
done

# ── 3. baseline ──────────────────────────────────────────────────────────────
step "POST /admin/scenario/reset — start from the baseline"
r=$(admin_post /admin/scenario/reset)
show "$r"
[[ $(jget ok "$r") == "True" ]] && ok "reset ok" || bad "reset failed"
[[ $(gx net-diagnostics | python3 -c "import sys,json;print(json.load(sys.stdin)['fault_type'])") == "none" ]] \
  && ok "baseline is healthy" || bad "baseline is not healthy"

# ── 4. the repeatability requirement ─────────────────────────────────────────
step "Run the WiFi demo $TAKES times using apply/reset alone — no make seed"
for take in $(seq 1 "$TAKES"); do
  printf '\n  \033[1m— take %s —\033[0m\n' "$take"

  staged=$(admin_post /admin/scenario/apply -H "Content-Type: application/json" \
    -d '{"scenario":"wifi_degraded"}')
  [[ $(jget ok "$staged") == "True" ]] && ok "staged wifi_degraded" || bad "apply failed"

  diag=$(gx net-diagnostics)
  fault=$(jget fault_type "$diag")
  [[ "$fault" == "device_band_stuck" ]] && ok "diagnostics: device_band_stuck (band-stuck first)" \
    || bad "expected device_band_stuck, got $fault"

  steer=$(device_action "band-steer" "$(jget primary_target "$diag")")
  [[ $(jget fault_cleared "$steer") == "True" ]] && ok "band-steer cleared it" || bad "band-steer failed"

  diag2=$(gx net-diagnostics)
  [[ $(jget fault_type "$diag2") == "extender_flapping" ]] && ok "diagnostics: extender_flapping" \
    || bad "expected extender_flapping, got $(jget fault_type "$diag2")"

  reboot=$(device_action "reboot-extender" "$(jget primary_target "$diag2")")
  [[ $(jget fault_cleared "$reboot") == "True" ]] && ok "reboot-extender cleared it" || bad "reboot failed"

  st=$(gx net-status)
  [[ $(jget healthy "$st") == "True" ]] && ok "network healthy — demo complete" || bad "not healthy"

  r=$(admin_post /admin/scenario/reset)
  [[ $(jget ok "$r") == "True" ]] && ok "reset for the next take" || bad "reset failed"
  [[ $(jget fault_type "$(gx net-diagnostics)") == "none" ]] && ok "back to baseline" || bad "reset left a fault"
done

# ── 5. another scenario, same machinery ──────────────────────────────────────
step "POST /admin/scenario/apply outage_in_area — a WAN fault outranks in-home ones"
admin_post /admin/scenario/apply -H "Content-Type: application/json" \
  -d '{"scenario":"outage_in_area"}' >/dev/null
diag=$(gx net-diagnostics)
show "$diag"
[[ $(jget fault_type "$diag") == "wan_degraded" ]] && ok "fault: wan_degraded" || bad "expected wan_degraded"
[[ $(jget recommended_action "$diag") == "escalate" ]] && ok "recommends escalate, not a pointless band-steer" \
  || bad "expected escalate"

# ── 6. event log ─────────────────────────────────────────────────────────────
step "GET /admin/events — every apply and reset is recorded"
events=$(curl -sS -u "$ADMIN" "$BASE/admin/events")
count=$(python3 -c "import sys,json;print(len(json.load(sys.stdin)))" <<<"$events")
[[ "$count" -gt 0 ]] && ok "$count events logged" || bad "event log is empty"
python3 -c "
import sys, json
for e in json.load(sys.stdin)[:6]:
    print(f\"    {e['created_at'][11:19]}  {e['action']:6} {e['scenario'] or '-':16} {e['summary']}\")
" <<<"$events"

# ── 7. back to baseline for the next presenter ───────────────────────────────
step "Leave it clean"
admin_post /admin/scenario/reset >/dev/null
[[ $(jget fault_type "$(gx net-diagnostics)") == "none" ]] && ok "baseline restored" || bad "not restored"

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
