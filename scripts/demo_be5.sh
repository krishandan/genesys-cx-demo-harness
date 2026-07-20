#!/usr/bin/env bash
# BE-5 walkthrough: the complete Demo-1 backend arc.
#
#   resolve → verify PIN → devices (match the named iPad) → diagnostics →
#   band-steer → net-status → offers → place → send-confirmation
#
# This is what AVA-1 (self-heal) and AVA-2 (upsell/order) call, in order.
#
#   ./scripts/demo_be5.sh
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
DEMO_PHONE="${DEMO_PHONE:-+447700900000}"
DEMO_PIN="${DEMO_PIN:-24680}"

pass=0
fail=0

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m✗ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
show() { python3 -m json.tool <<<"$1" | sed 's/^/  /'; }
jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"$2"; }

gx()  { curl -sS -G -H "X-API-Key: $API_KEY" --data-urlencode "identifier=$DEMO_PHONE" "$BASE/gx/$1"; }
post() { curl -sS -X POST "$BASE/gx/$1" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "$2"; }
order() {
  post order-action "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"$1\",\"target\":\"$2\"}"
}

printf '\033[1mBacklot BE-5 — Demo 1 backend arc — %s\033[0m\n' "$BASE"

# ── 0. stage the demo fault ──────────────────────────────────────────────────
step "Stage the demo (admin: apply wifi_degraded)"
staged=$(curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" \
  -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}')
grep -q '"ok": *true' <<<"$staged" && ok "wifi_degraded applied" || bad "could not stage: $staged"

# ── 1. who is this? ──────────────────────────────────────────────────────────
step "GET /gx/customer-context — resolve the caller"
ctx=$(gx customer-context)
name=$(jget display_name "$ctx")
[[ $(jget found "$ctx") == "True" ]] && ok "resolved $name" || bad "did not resolve $DEMO_PHONE"
[[ $(jget verified "$ctx") == "False" ]] \
  && ok "not yet verified — identity still has to be proven" || bad "should not be verified yet"

# ── 2. verify the 5-digit PIN ────────────────────────────────────────────────
step "POST /gx/verify-customer — the 5-digit PIN"
verified=$(post verify-customer \
  "{\"identifier\":\"$DEMO_PHONE\",\"factor_type\":\"pin\",\"factor_value\":\"$DEMO_PIN\"}")
show "$verified"
[[ $(jget verified "$verified") == "True" ]] && ok "verified with a 5-digit PIN" || bad "PIN did not verify"
[[ ${#DEMO_PIN} -eq 5 ]] && ok "PIN is 5 digits" || bad "PIN is ${#DEMO_PIN} digits, expected 5"

wrong=$(post verify-customer \
  "{\"identifier\":\"$DEMO_PHONE\",\"factor_type\":\"pin\",\"factor_value\":\"00000\"}")
[[ $(jget verified "$wrong") == "False" && -z $(jget party_id "$wrong") ]] \
  && ok "a wrong PIN verifies false and leaks nothing" || bad "wrong PIN leaked something"

# ── 3. the customer names a device ───────────────────────────────────────────
step "GET /gx/devices — the customer says \"Ella's iPad is terrible upstairs\""
devices=$(gx devices)
python3 -c "
import sys, json
for d in json.load(sys.stdin):
    print(f\"  {d['label']:18} {d['kind']:7} {d['band']:>4}GHz {d['rssi']:>5}dBm  {d['ap_label']:18} {d['status_summary']}\")
" <<<"$devices"

python3 -c "
import sys, json
rows = json.load(sys.stdin)
assert isinstance(rows, list), 'not a top-level array'
nested = [k for r in rows for k, v in r.items() if isinstance(v, (list, dict))]
sys.exit(1 if nested else 0)
" <<<"$devices" && ok "top-level array of flat objects" || bad "devices are not flat"

ipad=$(python3 -c "
import sys, json
rows = json.load(sys.stdin)
m = next((d for d in rows if d['label'] == \"Ella's iPad\"), None)
print(json.dumps(m) if m else '')
" <<<"$devices")
[[ -n "$ipad" ]] && ok "matched the named device: Ella's iPad" || bad "could not match Ella's iPad"
[[ $(jget band "$ipad") == "2.4" ]] && ok "and it is the faulted one ($(jget status_summary "$ipad"))" \
  || bad "the iPad is not faulted"
IPAD_ID=$(jget device_id "$ipad")

# ── 4. diagnose ──────────────────────────────────────────────────────────────
step "GET /gx/net-diagnostics — the flat verdict"
diag=$(gx net-diagnostics)
show "$diag"
[[ $(jget fault_type "$diag") == "device_band_stuck" ]] && ok "fault: device_band_stuck" \
  || bad "expected device_band_stuck, got $(jget fault_type "$diag")"
[[ $(jget primary_target_label "$diag") == "Ella's iPad" ]] \
  && ok "the verdict names the same device the customer did" || bad "verdict names a different device"
[[ $(jget primary_target "$diag") == "$IPAD_ID" ]] \
  && ok "and the same id /gx/devices returned" || bad "target id disagrees with /gx/devices"

# ── 5. fix it ────────────────────────────────────────────────────────────────
step "POST /gx/device-action — band-steer Ella's iPad"
steer=$(post device-action \
  "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"band-steer\",\"target\":$(python3 -c "import json,sys;print(json.dumps('$(jget primary_target "$diag")'))")}")
show "$steer"
[[ $(jget ok "$steer") == "True" ]] && ok "action applied" || bad "band-steer failed"
[[ $(jget fault_cleared "$steer") == "True" ]] && ok "fault_cleared" || bad "fault not cleared"

step "GET /gx/net-status — confirm the fix"
st=$(gx net-status)
[[ $(jget worst_device_band "$st") != "2.4" ]] && ok "no device left on the slow band" \
  || bad "a device is still on 2.4GHz"
ok "devices on the faster band: $(jget devices_on_target_band "$st")/$(jget device_total "$st")"

# ── 6. the upsell ────────────────────────────────────────────────────────────
step "GET /gx/offers — is there an upgrade worth offering?"
offer=$(gx offers)
show "$offer"
[[ $(jget eligible "$offer") == "True" ]] && ok "eligible: $(jget name "$offer") at £$(jget price_gbp "$offer")/mo" \
  || bad "expected an eligible offer"
ok "reason the agent can give: \"$(jget reason "$offer")\""
OFFER_ID=$(jget offer_id "$offer")

# ── 7. order it ──────────────────────────────────────────────────────────────
step "POST /gx/order-action place — order the upgrade"
placed=$(order place "$OFFER_ID")
show "$placed"
[[ $(jget ok "$placed") == "True" ]] && ok "order placed: $(jget status "$placed"), $(jget eta_text "$placed")" \
  || bad "place failed"
ORDER_ID=$(jget order_id "$placed")

step "POST /gx/order-action place again — must not double-order"
again=$(order place "$OFFER_ID")
[[ $(jget order_id "$again") == "$ORDER_ID" ]] && ok "idempotent: same order_id, no duplicate" \
  || bad "a second order was created"

# ── 8. confirm it ────────────────────────────────────────────────────────────
step "POST /gx/order-action send-confirmation"
sent=$(order send-confirmation "$ORDER_ID")
show "$sent"
[[ $(jget ok "$sent") == "True" ]] && ok "confirmation sent to $(jget sent_to_masked "$sent")" \
  || bad "send-confirmation failed"
grep -q "•" <<<"$(jget sent_to_masked "$sent")" && ok "address is masked, not recited" \
  || bad "the address was not masked"

step "POST /gx/order-action send-confirmation again — must not resend"
resent=$(order send-confirmation "$ORDER_ID")
[[ $(jget message_ref "$resent") == $(jget message_ref "$sent") ]] \
  && ok "idempotent: same message_ref" || bad "a second confirmation was sent"

# ── 9. error paths stay flat ─────────────────────────────────────────────────
step "Bad input returns a clean flat 4xx, never a 500"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/gx/order-action" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"place\",\"target\":\"NO-SUCH-OFFER\"}")
[[ "$code" == "404" ]] && ok "unknown offer → HTTP 404" || bad "expected 404, got $code"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/gx/order-action" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$DEMO_PHONE\",\"action\":\"refund-everything\",\"target\":\"x\"}")
[[ "$code" == "400" ]] && ok "unknown verb → HTTP 400" || bad "expected 400, got $code"

# ── 10. a second take starts clean ───────────────────────────────────────────
step "Reset — the next take must start clean (orders cleared too)"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null
[[ $(jget fault_type "$(gx net-diagnostics)") == "none" ]] && ok "network back to baseline" \
  || bad "reset left a fault"
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/apply" \
  -H "Content-Type: application/json" -d '{"scenario":"wifi_degraded"}' >/dev/null
retake=$(order place "$OFFER_ID")
[[ $(jget order_id "$retake") != "$ORDER_ID" ]] \
  && ok "take two places a genuinely new order" || bad "take two inherited take one's order"

# ── 11. contracts ────────────────────────────────────────────────────────────
step "Exported AVA-compliant contracts"
for f in contracts/devices.json contracts/offers.json contracts/order-action.json; do
  if [[ -f "$f" ]] && python3 -c "import json;json.load(open('$f'))" 2>/dev/null; then
    ok "$f present and valid"
  else
    bad "$f missing or invalid"
  fi
done
python3 -c "
import json, glob, sys
bad = []
for path in glob.glob('contracts/*.json'):
    d = json.load(open(path))
    if d.get('actionType') != 'custom':
        bad.append(f'{path}: missing actionType')
    text = json.dumps(d['contract'])
    for kw in ('oneOf','anyOf','allOf','\$ref','const','dependencies'):
        if f'\"{kw}\"' in text:
            bad.append(f'{path}: {kw}')
    schema = d['contract']['output']['successSchema']
    node = schema.get('items', schema)
    for name in node.get('properties', {}):
        if '.' in name:
            bad.append(f'{path}: dotted property {name}')
print('\n'.join(bad))
sys.exit(1 if bad else 0)
" && ok "every contract is AVA-compliant (actionType, no forbidden keywords, no dots)" \
  || bad "a contract is not AVA-compliant"

# ── leave it clean ───────────────────────────────────────────────────────────
curl -sS -u "$ADMIN" -X POST "$BASE/admin/scenario/reset" >/dev/null

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
