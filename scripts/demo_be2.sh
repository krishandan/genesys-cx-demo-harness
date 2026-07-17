#!/usr/bin/env bash
# BE-2 walkthrough: the WiFi self-healing engine.
# resolve → diagnose (fault) → band-steer → diagnose (next fault) → reboot-extender → recovered.
#
#   ./scripts/demo_be2.sh
#   RESET=0 ./scripts/demo_be2.sh   # skip the re-seed (e.g. against a remote BASE)
#
# Expects the stack up (make up) and seeded (make seed).
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
RESET="${RESET:-1}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
API_KEY="${API_KEY:-dev-local-key-change-me}"
DEMO_PHONE="${DEMO_PHONE:-+447700900000}"
HEALTHY_PHONE="${HEALTHY_PHONE:-+447700900001}"

pass=0
fail=0

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show() { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

gx() { curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=$2" "$BASE/gx/$1"; }

post_action() {
  curl -sS -X POST "$BASE/gx/device-action" \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"$1\",\"target\":\"$2\"}"
}

assert_flat() {
  python3 -c "
import sys, json
body = json.load(sys.stdin)
sys.exit(1 if [k for k, v in body.items() if isinstance(v, (list, dict))] else 0)
" <<<"$1"
}

printf '\033[1mBacklot BE-2 — WiFi self-healing — %s\033[0m\n' "$BASE"

# ── 0. reset to the staged baseline ──────────────────────────────────────────
# BE-2 seeds the degraded state directly; generalized apply/reset is BE-3, so a
# re-seed is what makes this walkthrough repeatable.
if [[ "$RESET" == "1" ]]; then
  step "Reset: re-seed the staged degraded baseline"
  if docker compose exec -T api python -m app.seed --tenant northwind >/dev/null 2>&1; then
    ok "re-seeded northwind"
  else
    bad "could not re-seed (is the stack up? use RESET=0 for a remote BASE)"
  fi
fi

# ── 1. who is this? ──────────────────────────────────────────────────────────
step "GET /gx/customer-context — resolve the demo subscriber"
ctx=$(gx customer-context "$DEMO_PHONE")
name=$(jget display_name "$ctx")
[[ $(jget found "$ctx") == "True" ]] && ok "resolved $name" || bad "did not resolve $DEMO_PHONE"

# ── 2. diagnose ──────────────────────────────────────────────────────────────
step "GET /gx/net-diagnostics — the flat verdict, not the topology"
diag=$(gx net-diagnostics "$DEMO_PHONE")
show "$diag"
assert_flat "$diag" && ok "verdict is flat (no nested arrays)" || bad "verdict has nested values"
[[ $(jget fault_type "$diag") == "device_band_stuck" ]] \
  && ok "fault: device_band_stuck" || bad "expected device_band_stuck, got $(jget fault_type "$diag")"
[[ $(jget wan_ok "$diag") == "True" ]] && ok "WAN is healthy: the fault is inside the home" || bad "wan_ok should be true"
device_id=$(jget primary_target "$diag")
device_label=$(jget primary_target_label "$diag")
ok "AVA can name the device without walking the topology: '$device_label'"

# ── 3. first fix: band-steer ─────────────────────────────────────────────────
step "POST /gx/device-action — band-steer '$device_label'"
steer=$(post_action "band-steer" "$device_id")
show "$steer"
[[ $(jget ok "$steer") == "True" ]] && ok "action applied" || bad "band-steer failed"
[[ $(jget fault_cleared "$steer") == "True" ]] && ok "fault_cleared" || bad "fault not cleared"

# ── 4. diagnose again: the next fault surfaces ───────────────────────────────
step "GET /gx/net-diagnostics — state actually mutated, next fault shows"
diag2=$(gx net-diagnostics "$DEMO_PHONE")
show "$diag2"
[[ $(jget fault_type "$diag2") == "extender_flapping" ]] \
  && ok "fault: extender_flapping" || bad "expected extender_flapping, got $(jget fault_type "$diag2")"
ap_id=$(jget primary_target "$diag2")
ap_label=$(jget primary_target_label "$diag2")

# ── 5. second fix: reboot-extender ───────────────────────────────────────────
step "POST /gx/device-action — reboot-extender '$ap_label'"
reboot=$(post_action "reboot-extender" "$ap_id")
show "$reboot"
[[ $(jget ok "$reboot") == "True" ]] && ok "action applied" || bad "reboot-extender failed"
[[ $(jget fault_cleared "$reboot") == "True" ]] && ok "fault_cleared" || bad "fault not cleared"

# ── 6. confirm recovery ──────────────────────────────────────────────────────
step "GET /gx/net-status — confirm recovery"
st=$(gx net-status "$DEMO_PHONE")
show "$st"
assert_flat "$st" && ok "status is flat" || bad "status has nested values"
[[ $(jget healthy "$st") == "True" ]] && ok "network is healthy" || bad "expected healthy"
[[ $(jget fault_type "$st") == "none" ]] && ok "no faults remain" || bad "fault remains"
[[ $(jget extender_status "$st") == "online" ]] && ok "extender back online" || bad "extender not online"

# ── 7. a healthy subscriber was never broken ─────────────────────────────────
step "GET /gx/net-diagnostics — a healthy subscriber reports no fault"
healthy=$(gx net-diagnostics "$HEALTHY_PHONE")
[[ $(jget fault_type "$healthy") == "none" ]] && ok "fault_type: none" || bad "healthy subscriber shows a fault"

# ── 8. error paths stay clean ────────────────────────────────────────────────
step "Bad input returns a clean flat 4xx, never a 500"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/gx/device-action" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"band-steer\",\"target\":\"not-a-real-target\"}")
[[ "$code" == "404" ]] && ok "unknown target → HTTP 404" || bad "expected 404, got $code"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/gx/device-action" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"reticulate-splines\",\"target\":\"x\"}")
[[ "$code" == "400" ]] && ok "unknown action → HTTP 400" || bad "expected 400, got $code"

# ── 9. contracts ─────────────────────────────────────────────────────────────
step "Exported data-action contracts"
for f in contracts/net-diagnostics.json contracts/net-status.json contracts/device-action.json; do
  if [[ -f "$f" ]] && python3 -c "import json;json.load(open('$f'))" 2>/dev/null; then
    ok "$f present and valid"
  else
    bad "$f missing or invalid"
  fi
done

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
