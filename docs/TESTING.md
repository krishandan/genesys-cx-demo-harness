# gx endpoint testing reference

**Source of truth for Genesys data-action testing and for writing AVA tool instructions.**

Every field name, type and `required` flag below is taken from the generated contracts in
`contracts/*.json`. Every response was **verified by calling the running API** (local
`http://localhost:8000`, Northwind seed) on 2026-07-21, resetting to the seeded baseline
between captures. Where a value is quoted as a response, it came back from a real call —
not from the phase briefs.

Do not hand-edit this file to match an assumption; regenerate the facts by re-running the
calls shown here.

---

## Conventions that apply to every endpoint

- **Auth:** `X-API-Key: <key>` header on every call. Missing/invalid key → `401`. In
  Genesys this binds as `${credentials.apiKey}` from the integration credential.
- **Tenant:** single-tenant box; there is **no** tenant input on any contract. The API
  uses `DEFAULT_TENANT` (northwind). (An optional `X-Tenant` header exists on the server
  but is deliberately not in the contracts — see the field-name flags.)
- **Base URL Genesys binds to:** `https://backlot-api.krishharness.com`. The `requestUrlTemplate`
  in each contract already carries it.
- **Every response is flat** (scalars only, no nested arrays/objects). `/gx/devices` and
  `/gx/telemetry` return a **top-level array** of flat objects; all others return a single
  flat object.
- **Not-found is a `200`, not an error**, for the read endpoints — the full flat shape
  comes back with `found: false` and empty fields, so a flow binds the same keys on both
  branches. POST verbs use flat `4xx` for bad input (body still flat, never nested under
  `detail`).
- **`params` and other empty-string inputs:** several POST inputs are marked `required` in
  the contract but accept an empty string `""`. This is the template-referenced-required
  rule: an input referenced in the Velocity body/URL must be `required`, because an
  unsupplied optional renders as the literal `${input.x}` and breaks the request. Pass
  `""`, never omit. Each is flagged below.

### Seed constants (Northwind, verified)

| Thing | Value |
| --- | --- |
| Demo subscriber (phone) | `+447700900000` — Anne Clark-Phillips |
| — party_id | `dde8cc6c-f2a6-5057-9f4f-2dbd24e4a432` |
| — email | `anne.clark-phillips.0@example.net` |
| — account_no | `NW000000` |
| — national form (also resolves) | `07700900000` |
| — tier | `bronze` |
| Verify factor | `factor_type: pin`, `factor_value: 24680` (**5 digits**) |
| Offer | `offer_id: NW-MESH-PRO` — Northwind Mesh Pro, £6.00/mo |
| Healthy subscribers (no offer, no fault) | `+447700900001`, `002`, `003` |
| Parties with no home network | `+447700900004` … `+447700900009` |
| Unknown subscriber (for negative tests) | `+447700900999` |

**Device ids** (deterministic `uuid5`, stable across reseeds — but in a live flow the agent
gets these from `/gx/devices` or `/gx/net-diagnostics`, it does not hardcode them):

| Device | kind | device_id |
| --- | --- | --- |
| Anne's Phone | phone | `a2aefbbb-2102-50ca-b173-cb5fb76f342a` |
| Ella's iPad | tablet | `963286b0-80ec-5a78-874f-2421a8531478` ← the device `wifi_degraded` faults |
| Living Room TV | tv | `d0b1577f-d163-597e-8741-fd79f9015bbe` |
| Work Laptop | laptop | `4a0e6e37-afd9-5d0a-a91f-ee5717949b37` |
| Upstairs Extender (ap, for reboot-extender) | extender ap | `3b2dbbf3-ffac-5d4b-9874-44c389d1c362` |

---

## 1. `GET /gx/customer-context`

Resolve a subscriber by any identifier. Identity is **not** confirmed here.

**Inputs**

| name | type | required | sample |
| --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` (or email / `NW000000` / `07700900000`) |

**Response** (verified, baseline)

```json
{
  "found": true,
  "party_id": "dde8cc6c-f2a6-5057-9f4f-2dbd24e4a432",
  "display_name": "Anne Clark-Phillips",
  "tenant_slug": "northwind",
  "tier": "bronze",
  "verified": false,
  "last_channel": "sms",
  "id_type_resolved": "phone"
}
```

| field | type | baseline value / meaning |
| --- | --- | --- |
| `found` | boolean | `true` when resolved |
| `party_id` | string | internal id; carries into no other gx input (masked from the agent) |
| `display_name` | string | `Anne Clark-Phillips` |
| `tenant_slug` | string | `northwind` |
| `tier` | string | `bronze` |
| `verified` | boolean | **always `false`** — verification is the separate `verify-customer` call |
| `last_channel` | string | `sms` at baseline (spine-derived); becomes the last real interaction channel once one is recorded |
| `id_type_resolved` | string | `phone` \| `email` \| `account_no` \| `msisdn` \| `account_no` (fallback) |

- `id_type_resolved` for email → `email`, account → `account_no`, national `07700…` → `phone`.
- **Use `found`, not `id_type_resolved`, to decide existence.** A garbage string like
  `not-an-identifier` returns `found: false` **and** `id_type_resolved: account_no` (the
  normalizer's fallback classification), so the type field is not an existence signal.

**Negative — unknown identifier** (`+447700900999`, verified, still `200`):

```json
{
  "found": false, "party_id": "", "display_name": "", "tenant_slug": "northwind",
  "tier": "", "verified": false, "last_channel": "", "id_type_resolved": "phone"
}
```

---

## 2. `POST /gx/verify-customer`

Confirm a factor. A wrong factor returns `verified: false` and leaks nothing (no `party_id`).

**Inputs** (body)

| name | type | required | sample |
| --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` |
| `factor_type` | string | yes | `pin` (must be literally `pin` for the seed) |
| `factor_value` | string | yes | `24680` |

**Response — correct PIN** (verified)

```json
{ "verified": true, "party_id": "dde8cc6c-f2a6-5057-9f4f-2dbd24e4a432", "masked_name": "A*** C***" }
```

| field | type | meaning |
| --- | --- | --- |
| `verified` | boolean | `true` only on a matching factor |
| `party_id` | string | empty unless verified |
| `masked_name` | string | `A*** C***` (reveal 1 char, fixed 3-mask, per tenant config) |

**Negatives** (both verified, `200`):

- Wrong PIN (`00000`): `{ "verified": false, "party_id": "", "masked_name": "" }`
- Wrong `factor_type` (`dob` with value `24680`): `{ "verified": false, "party_id": "", "masked_name": "" }` — only `pin` is seeded.

---

## 3. `GET /gx/devices`

Every device in the home, **weakest signal first** — the tool for matching a device the
customer *names*. **Top-level array** of flat objects. Unknown/no-network → `[]` (still `200`).

**Inputs**

| name | type | required | sample |
| --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` |

**Response item fields**

| field | type | meaning |
| --- | --- | --- |
| `device_id` | string | pass to `device-action` as `target` (masked from the agent's speech) |
| `label` | string | e.g. `Ella's iPad` — match against what the customer says |
| `kind` | string | `phone` \| `tablet` \| `laptop` \| `tv` |
| `band` | string | `2.4` or `5` |
| `rssi` | integer | dBm; nearer 0 is better, below −70 is poor |
| `ap_label` | string | `Living Room Hub` or `Upstairs Extender` |
| `steer_eligible` | boolean | can a band-steer help it |
| `status_summary` | string | speakable phrase, e.g. `weak signal on the slower band` |

**Ordering guarantee:** ascending `rssi` (weakest first). Verified baseline order:

| label | band | rssi | status_summary |
| --- | --- | --- | --- |
| Work Laptop | 5 | −61 | good signal on the faster band |
| Ella's iPad | 5 | −55 | good signal on the faster band |
| Living Room TV | 5 | −52 | good signal on the faster band |
| Anne's Phone | 5 | −48 | good signal on the faster band |

**Under `wifi_degraded`** (verified) — Ella's iPad drops to the front:

| label | band | rssi | status_summary |
| --- | --- | --- | --- |
| Ella's iPad | 2.4 | −78 | weak signal on the slower band |
| Work Laptop | 5 | −61 | good signal on the faster band |
| Living Room TV | 5 | −52 | good signal on the faster band |
| Anne's Phone | 5 | −48 | good signal on the faster band |

---

## 4. `GET /gx/net-diagnostics`

The flat fault verdict. AVA branches on `fault_type` and acts on `primary_target`.

**Inputs**

| name | type | required | sample |
| --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` |

**Response fields**

| field | type | meaning |
| --- | --- | --- |
| `found` | boolean | `false` → no subscriber (still `200`) |
| `party_id` | string | internal id |
| `fault_type` | string | `device_band_stuck` \| `extender_flapping` \| `wan_degraded` \| `none` |
| `primary_target` | string | **opaque id to pass to `device-action` as `target`** |
| `primary_target_kind` | string | `device` \| `ap` \| `gateway` |
| `primary_target_label` | string | human name, e.g. `Ella's iPad` |
| `recommended_action` | string | `band-steer` \| `reboot-extender` \| `escalate` \| `none` |
| `wan_ok` | boolean | broadband line healthy |
| `worst_device_band` | string | band of the weakest device |
| `worst_device_rssi` | integer | signal of the weakest device |
| `extender_status` | string | `online` \| `flapping` \| `offline` \| `none` |

**Baseline (healthy)** — verified:

```json
{ "found": true, "party_id": "dde8cc6c-…", "fault_type": "none", "primary_target": "",
  "primary_target_kind": "", "primary_target_label": "", "recommended_action": "none",
  "wan_ok": true, "worst_device_band": "5", "worst_device_rssi": -61, "extender_status": "online" }
```

> Note: at healthy baseline `worst_device_*` is the weakest **healthy** device (Work Laptop,
> −61), *not* a fault. "worst" means weakest, not faulty — branch on `fault_type`.

**Under `wifi_degraded`** — verified:

```json
{ "found": true, "party_id": "dde8cc6c-…", "fault_type": "device_band_stuck",
  "primary_target": "963286b0-80ec-5a78-874f-2421a8531478", "primary_target_kind": "device",
  "primary_target_label": "Ella's iPad", "recommended_action": "band-steer", "wan_ok": true,
  "worst_device_band": "2.4", "worst_device_rssi": -78, "extender_status": "flapping" }
```

**After `band-steer`** (re-diagnose) — verified; the next fault surfaces by precedence:

```json
{ "found": true, "party_id": "dde8cc6c-…", "fault_type": "extender_flapping",
  "primary_target": "3b2dbbf3-ffac-5d4b-9874-44c389d1c362", "primary_target_kind": "ap",
  "primary_target_label": "Upstairs Extender", "recommended_action": "reboot-extender",
  "wan_ok": true, "worst_device_band": "5", "worst_device_rssi": -61, "extender_status": "flapping" }
```

**Fault precedence** (config, least-disruptive-remedy-first):
`wan_degraded` → `device_band_stuck` → `extender_flapping`. Two faults are staged at once;
`device_band_stuck` reports first, so the demo runs **band-steer, then reboot-extender**.

**Negative — unknown identifier:** `{ "found": false, "fault_type": "", … }` (all empty, `200`).
Parties `+447700900004…009` have no network → also `found: false`.

---

## 5. `GET /gx/net-status`

Current full network state, for confirming recovery after an action.

**Inputs:** `identifier` (string, required) → `+447700900000`.

**Response fields** (verified values at baseline / degraded):

| field | type | baseline | under `wifi_degraded` |
| --- | --- | --- | --- |
| `found` | boolean | `true` | `true` |
| `party_id` | string | dde8cc6c-… | dde8cc6c-… |
| `healthy` | boolean | `true` | `false` |
| `fault_type` | string | `none` | `device_band_stuck` |
| `wan_ok` | boolean | `true` | `true` |
| `wan_status` | string | `online` | `online` |
| `gateway_model` | string | `Northwind Hub 6` | `Northwind Hub 6` |
| `gateway_uptime_s` | integer | `482913` | `482913` |
| `ap_total` | integer | `2` | `2` |
| `ap_online` | integer | `2` | `1` (extender flapping) |
| `extender_status` | string | `online` | `flapping` |
| `device_total` | integer | `4` | `4` |
| `devices_on_target_band` | integer | `4` | `3` |
| `worst_device_label` | string | `Work Laptop` | `Ella's iPad` |
| `worst_device_band` | string | `5` | `2.4` |
| `worst_device_rssi` | integer | `-61` | `-78` |

**After the full self-heal** (band-steer → reboot-extender) — verified:
`healthy: true`, `fault_type: none`, `ap_online: 2/2`, `extender_status: online`,
`devices_on_target_band: 4/4`.

> `devices_on_target_band` = count of devices on the **5GHz** band (the configured target
> band), not a list. `worst_device_*` at baseline is the weakest healthy device, not a fault.

---

## 6. `POST /gx/device-action`

Run a network verb. Verbs: `band-steer`, `reboot-extender`, `reboot-ap`. Idempotent per
committed state; `fault_cleared` is re-read from the DB after the action.

**Inputs** (body)

| name | type | required | sample | note |
| --- | --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` | |
| `action` | string | yes | `band-steer` | `band-steer` \| `reboot-extender` \| `reboot-ap` |
| `target` | string | yes | `963286b0-…` | **the `primary_target` from net-diagnostics — the id, NOT the label** |
| `params` | string | yes | `""` | required-but-empty; pass `""` for default behaviour |

**Response fields**

| field | type | meaning |
| --- | --- | --- |
| `ok` | boolean | action applied |
| `action` | string | echoes the verb |
| `target` | string | echoes the id |
| `result_summary` | string | speakable summary of what changed |
| `fault_cleared` | boolean | the targeted fault is now gone |

**`band-steer` on Ella's iPad under `wifi_degraded`** — verified:

```json
{ "ok": true, "action": "band-steer", "target": "963286b0-80ec-5a78-874f-2421a8531478",
  "result_summary": "Moved Ella's iPad from 2.4GHz to 5GHz; signal -78 → -56 dBm",
  "fault_cleared": true }
```

**`reboot-extender` on the Upstairs Extender ap** — verified:

```json
{ "ok": true, "action": "reboot-extender", "target": "3b2dbbf3-ffac-5d4b-9874-44c389d1c362",
  "result_summary": "Rebooted Upstairs Extender: went offline and came back flapping → online; backhaul 34 → 92",
  "fault_cleared": true }
```

**Negative — unknown `target`** (`00000000-…`) — verified, **HTTP 404**, flat:

```json
{ "ok": false, "action": "band-steer", "target": "00000000-0000-0000-0000-000000000000",
  "result_summary": "No such target '00000000-0000-0000-0000-000000000000' for this subscriber",
  "fault_cleared": false }
```

---

## 7. `GET /gx/offers`

The single best upgrade the subscriber's own topology justifies. `eligible: false` and
`found: false` share the full key set with the eligible shape.

**Inputs:** `identifier` (string, required) → `+447700900000`.

**Response fields**

| field | type | meaning |
| --- | --- | --- |
| `found` | boolean | `false` → no subscriber / no network |
| `eligible` | boolean | `true` → there is an offer worth making |
| `offer_id` | string | pass to `order-action` `place` as `target` |
| `name` | string | `Northwind Mesh Pro` |
| `price_gbp` | **number** | `6.0` (a float, not an integer) |
| `reason` | string | customer-specific justification |

**Eligible** (demo subscriber, verified — eligible at baseline *and* after the self-heal):

```json
{ "found": true, "eligible": true, "offer_id": "NW-MESH-PRO", "name": "Northwind Mesh Pro",
  "price_gbp": 6.0,
  "reason": "it puts a second mesh point upstairs, where a device is currently hanging on at the edge of the booster's range" }
```

**Not eligible** — a healthy standard home (`+447700900001`, verified):
`{ "found": true, "eligible": false, "offer_id": "", "name": "", "price_gbp": 0.0, "reason": "" }`

**Negative — unknown identifier:** `{ "found": false, "eligible": false, "offer_id": "", "name": "", "price_gbp": 0.0, "reason": "" }`.

---

## 8. `POST /gx/order-action`

Place an order, then confirm it. Verbs: `place`, `send-confirmation`. Both idempotent per
order. **One output shape covers both verbs** — fields a verb doesn't produce come back empty.

**Inputs** (body)

| name | type | required | sample | note |
| --- | --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` | |
| `action` | string | yes | `place` | `place` \| `send-confirmation` |
| `target` | string | yes | `NW-MESH-PRO` | **dual meaning: `offer_id` for `place`, `order_id` for `send-confirmation`** |
| `params` | string | yes | `""` | required-but-empty; unused, pass `""` |

**Response fields**

| field | type | after `place` | after `send-confirmation` |
| --- | --- | --- | --- |
| `ok` | boolean | `true` | `true` |
| `action` | string | `place` | `send-confirmation` |
| `order_id` | string | new uuid (carries into `send-confirmation.target`) | echoes it |
| `status` | string | `placed` | `confirmed` |
| `eta_text` | string | `arrives in 3–5 working days` | same |
| `sent_to_masked` | string | `""` | `a••••@example.net` (masked, • = U+2022) |
| `message_ref` | string | `""` | `MSG-<first 8 of order_id, upper>` |
| `result_summary` | string | `Ordered Northwind Mesh Pro at £6.00 per month; …` | `Confirmation sent to a••••@example.net` |

**`place`** (verified):

```json
{ "ok": true, "action": "place", "order_id": "d65ff48b-7135-454d-bccd-c099f3fad08d",
  "status": "placed", "eta_text": "arrives in 3–5 working days", "sent_to_masked": "",
  "message_ref": "", "result_summary": "Ordered Northwind Mesh Pro at £6.00 per month; arrives in 3–5 working days" }
```

**`send-confirmation`** with `target` = that `order_id` (verified):

```json
{ "ok": true, "action": "send-confirmation", "order_id": "d65ff48b-…", "status": "confirmed",
  "eta_text": "arrives in 3–5 working days", "sent_to_masked": "a••••@example.net",
  "message_ref": "MSG-D65FF48B", "result_summary": "Confirmation sent to a••••@example.net" }
```

- `order_id` is a fresh uuid per order — **not** hardcodable; it is produced by `place` and
  consumed by `send-confirmation`.
- Idempotency: a second `place` for the same offer returns the **same** `order_id` with
  `result_summary` "… was already ordered …"; a second `send-confirmation` returns the same
  `message_ref` with "… had already been sent …".

**Negative — unknown `offer_id`** (`NO-SUCH`) — verified, **HTTP 404**, flat:

```json
{ "ok": false, "action": "place", "order_id": "", "status": "", "eta_text": "",
  "sent_to_masked": "", "message_ref": "", "result_summary": "No offer 'NO-SUCH' in the catalogue" }
```

Unknown verb → flat `400`; empty `target` → flat `400`; unknown/`non-uuid` `order_id` → flat `404`.

---

## 9. `POST /gx/interaction-event`

Record an interaction; drives `customer-context.last_channel`.

**Inputs** (body)

| name | type | required | sample | note |
| --- | --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` | |
| `channel` | string | yes | `webmessaging` | `webmessaging` \| `voice` \| `sms` \| `email` \| … ; empty → `400` |
| `kind` | string | yes | `inbound` | required-but-defaultable: **pass `""` and it stores `inbound`** |

**Response** (verified):

```json
{ "ok": true, "party_id": "dde8cc6c-…", "stored": true, "last_channel": "webmessaging" }
```

| field | type | meaning |
| --- | --- | --- |
| `ok` / `stored` | boolean | recorded |
| `party_id` | string | internal id |
| `last_channel` | string | echoes the channel `customer-context` will now report |

- Empty `kind` (`""`) is stored as `inbound` (verified). Unknown identifier → flat `404`;
  empty `channel` → flat `400`.

---

## 10. `POST /gx/csat`

Write a satisfaction score back.

**Inputs** (body)

| name | type | required | sample | note |
| --- | --- | --- | --- | --- |
| `identifier` | string | yes | `+447700900000` | |
| `score` | **integer** | yes | `5` | 1–5; sent **unquoted** in the JSON body; out of range → `400` |
| `comment` | string | yes | `Sorted my wifi` | required-but-empty; pass `""` if none |
| `conversation_ref` | string | yes | `conv-abc-123` | required-but-empty; pass `""` if none |

**Response** (verified):

```json
{ "ok": true, "party_id": "dde8cc6c-…", "stored": true }
```

**Negative — score out of range** (`9`) — verified, **HTTP 400**, flat:
`{ "ok": false, "party_id": "", "stored": false }`. Unknown identifier → flat `404`.

---

## 11. `GET /gx/telemetry`

Proactive seam (not consumed by Genesys in M1). **Top-level array**, newest first; empty
`[]` for an unknown or healthy subscriber.

**Inputs:** `identifier` (string, required) → `+447700900000`.

**Response item fields:** `party_id`, `kind` (`network.degraded`), `fault_type`,
`primary_target`, `primary_target_kind`, `primary_target_label`, `recommended_action`,
`conversation_ref`, `occurred_at` (ISO-8601 string) — all scalars.

- **Baseline / healthy:** `[]` (verified).
- **Under `wifi_degraded`** (verified) — one event mirroring the verdict:

```json
[ { "party_id": "dde8cc6c-…", "kind": "network.degraded", "fault_type": "device_band_stuck",
    "primary_target": "963286b0-80ec-5a78-874f-2421a8531478", "primary_target_kind": "device",
    "primary_target_label": "Ella's iPad", "recommended_action": "band-steer",
    "conversation_ref": "", "occurred_at": "2026-07-21T17:28:09.995618+00:00" } ]
```

---

## Demo 1 walkthrough — the exact AVA call sequence

Concrete inputs in order, with the **carry** column showing which output value becomes the
next call's input. This is the chaining the agent performs. (Precondition: the demo fault is
staged — operator applies `wifi_degraded`; between takes, `/admin/scenario/reset`.)

| # | Call | Key inputs | Key outputs | Carries into next |
| --- | --- | --- | --- | --- |
| 1 | `GET customer-context` | `identifier=+447700900000` | `found:true`, `display_name:"Anne Clark-Phillips"`, `verified:false` | identifier reused throughout |
| 2 | `POST verify-customer` | `identifier=+447700900000`, `factor_type=pin`, `factor_value=24680` | `verified:true`, `masked_name:"A*** C***"` | gate: proceed only if `verified:true` |
| 3 | `GET devices` | `identifier=+447700900000` | `Ella's iPad` at `2.4`/`-78`, `device_id=963286b0-…` | matches the device the customer named |
| 4 | `GET net-diagnostics` | `identifier=+447700900000` | `fault_type:device_band_stuck`, `primary_target:963286b0-…`, `recommended_action:band-steer`, `primary_target_label:"Ella's iPad"` | **`primary_target` → step 5 `target`** |
| 5 | `POST device-action` | `action=band-steer`, `target=963286b0-…`, `params=""` | `ok:true`, `fault_cleared:true` | — |
| 6 | `GET net-diagnostics` (again) | `identifier=+447700900000` | `fault_type:extender_flapping`, `primary_target:3b2dbbf3-…` (kind `ap`), `recommended_action:reboot-extender` | **`primary_target` → step 7 `target`** |
| 7 | `POST device-action` | `action=reboot-extender`, `target=3b2dbbf3-…`, `params=""` | `ok:true`, `fault_cleared:true` | — |
| 8 | `GET net-status` | `identifier=+447700900000` | `healthy:true`, `fault_type:none`, `ap_online:2`, `devices_on_target_band:4` | confirms recovery to the customer |
| 9 | `GET offers` | `identifier=+447700900000` | `eligible:true`, `offer_id:NW-MESH-PRO`, `price_gbp:6.0`, `reason:"…"` | **`offer_id` → step 10 `target`** |
| 10 | `POST order-action` | `action=place`, `target=NW-MESH-PRO`, `params=""` | `ok:true`, `order_id:<uuid>`, `status:placed` | **`order_id` → step 11 `target`** |
| 11 | `POST order-action` | `action=send-confirmation`, `target=<order_id>`, `params=""` | `sent_to_masked:"a••••@example.net"`, `message_ref:MSG-…` | — |
| 12 | `POST csat` | `score=5`, `comment=""`, `conversation_ref=<conv id or "">` | `ok:true`, `stored:true` | — |

Two chaining points are the whole game and are easy to get wrong:
1. **`net-diagnostics.primary_target` → `device-action.target`** — the opaque id, not the label.
2. **`offers.offer_id` → `order-action(place).target` → `order-action(send-confirmation).target = order_id`** — the `target` field changes meaning between the two order verbs.

(Optional: `POST interaction-event` at the start of the conversation to set `last_channel`.)

---

## Field names that differ from what the endpoint's purpose suggests

Flags for whoever writes the AVA tool instructions:

1. **`device-action.target` and `order-action.target` are opaque ids, and `order-action.target`
   is dual-purpose.** For `device-action` and `order-action(place)` it is the id from the
   prior read (`primary_target` / `offer_id`); for `order-action(send-confirmation)` the same
   field is the `order_id` from `place`. Never pass a human label.
2. **`net-diagnostics.primary_target` vs `primary_target_label`.** Act on `primary_target`
   (the id); speak `primary_target_label`. Passing the label to `device-action` fails `404`.
3. **`params` is `required` on `device-action` and `order-action`, but must be `""`.** It is
   never populated in Demo 1. Same for `csat.comment`, `csat.conversation_ref`, and
   `interaction-event.kind` — all `required` in the contract but accept `""` (kind `""` → `inbound`).
4. **`customer-context.verified` is always `false`.** It is not the verification result —
   that is the separate `verify-customer` call. Do not read context `verified` as "authenticated".
5. **`id_type_resolved` is populated even when `found:false`** (a garbage string classifies as
   `account_no`). Use `found` for existence, not this field.
6. **`worst_device_*` (net-diagnostics, net-status) means *weakest*, not *faulty*.** At healthy
   baseline it is the weakest healthy device (−61 dBm). Branch on `fault_type` / `healthy`.
7. **`net-status.devices_on_target_band` is a count on the 5GHz band, not a list**, and "target
   band" is the configured fast band (`5`), which the field name assumes you know.
8. **`offers.price_gbp` is a `number` (float), e.g. `6.0`** — not an integer, and not a
   formatted string. The formatted `£6.00` only appears inside `order-action.result_summary`.
9. **`factor_type` must be literally `pin`.** `dob`, `zip`, `last4` are described in the input
   but only `pin` is seeded, so anything else returns `verified:false`.
10. **`sent_to_masked` uses `•` (U+2022 bullet), not `*`.** (Name masking in `verify-customer`
    uses `*`; email masking here uses `•`.)
11. **No `tenant` input exists on any contract**, though the server supports an `X-Tenant`
    header. Single-tenant box; do not add one to a data action (an unsupplied optional would
    render as a literal `${input.tenant}` and break the request).

---

## Reproducing these facts

```bash
# baseline
curl -s -u "$ADMIN_USER:$ADMIN_PASSWORD" -X POST localhost:8000/admin/scenario/reset
# stage the demo fault
curl -s -u "$ADMIN_USER:$ADMIN_PASSWORD" -X POST localhost:8000/admin/scenario/apply \
  -H 'Content-Type: application/json' -d '{"scenario":"wifi_degraded"}'
# any gx read
curl -s -H "X-API-Key: $API_KEY" -G --data-urlencode 'identifier=+447700900000' \
  localhost:8000/gx/net-diagnostics | python3 -m json.tool
```

Contracts regenerate with `python -m app.gx.contracts` (or `make contracts`); a drift test
fails if the committed files fall behind the code.
