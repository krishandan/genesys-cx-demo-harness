"""Flat, contract-safe gx shapes.

Every field is a scalar. No lists, no nested objects, no nulls: Genesys data action
output contracts cannot express nested arrays, and a consistent shape means a flow can
bind every field once and branch on `found` / `verified` rather than handling absent
properties.

**Descriptions are functional, not documentation.** Each of these endpoints becomes a
tool for the Agentic Virtual Agent, and the agent reads these descriptions to decide
when to call a tool and what a field means. Generation fails on a missing one
(`app/gx/ava.py`), so write them for the agent, not for a developer.
"""

from pydantic import BaseModel, Field


class CustomerContextOut(BaseModel):
    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = Field(
        default="",
        description="Internal subscriber id. Pass to other tools; never read it aloud.",
    )
    display_name: str = Field(
        default="", description="The subscriber's full name, for greeting them."
    )
    tenant_slug: str = Field(
        default="", description="The brand this subscriber belongs to, e.g. northwind."
    )
    tier: str = Field(
        default="",
        description=(
            "Account tier: bronze, silver or gold. Higher tiers may warrant more "
            "latitude."
        ),
    )
    verified: bool = Field(
        default=False,
        description=(
            "Always false here. Identity is NOT yet confirmed — call verify-customer "
            "with a PIN before doing anything account-specific."
        ),
    )
    last_channel: str = Field(
        default="",
        description=(
            "The channel this subscriber last contacted us on, e.g. webmessaging, "
            "sms, voice."
        ),
    )
    id_type_resolved: str = Field(
        default="",
        description=(
            "What the identifier matched: phone, email, account_no, msisdn, or "
            "unrecognized when it could not be parsed."
        ),
    )


class VerifyCustomerIn(BaseModel):
    identifier: str
    factor_type: str = Field(description="dob | zip | pin | last4")
    factor_value: str


class VerifyCustomerOut(BaseModel):
    verified: bool = Field(
        description=(
            "True only when the supplied factor matched. If false, identity is not "
            "confirmed — do not disclose or change account details."
        )
    )
    party_id: str = Field(
        default="",
        description="Internal subscriber id, empty unless verified. Never read it aloud.",
    )
    masked_name: str = Field(
        default="",
        description=(
            "The subscriber's name with most letters masked, e.g. 'A*** C***'. Safe to "
            "use to confirm who verified without reciting their full name."
        ),
    )


class NetDiagnosticsOut(BaseModel):
    """The flat verdict. AVA branches on fault_type and acts on primary_target — it
    never walks the topology, which is what keeps this contract-safe."""

    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = Field(
        default="", description="Internal subscriber id. Never read it aloud."
    )
    fault_type: str = Field(
        default="",
        description=(
            "The single fault to act on: device_band_stuck (a device is on the slow "
            "band with a weak signal), extender_flapping (a booster keeps dropping), "
            "wan_degraded (the line into the home is down — cannot be self-healed), or "
            "none when the network is healthy."
        ),
    )
    primary_target: str = Field(
        default="",
        description=(
            "Opaque id of the thing to fix. Pass it straight to device-action as "
            "'target'. Never read it aloud."
        ),
    )
    primary_target_kind: str = Field(
        default="", description="What the target is: device, ap, or gateway."
    )
    primary_target_label: str = Field(
        default="",
        description=(
            "Human name of the faulty thing, e.g. \"Ella's iPad\". Use this when telling "
            "the customer what you found."
        ),
    )
    recommended_action: str = Field(
        default="",
        description=(
            "The device-action verb to call next: band-steer, reboot-extender, "
            "escalate (a human must handle it), or none."
        ),
    )
    wan_ok: bool = Field(
        default=False,
        description="True when the broadband line into the home is healthy.",
    )
    worst_device_band: str = Field(
        default="",
        description=(
            "Wi-Fi band of the weakest device: 2.4 (slower, longer range) or 5 (faster)."
        ),
    )
    worst_device_rssi: int = Field(
        default=0,
        description=(
            "Signal strength of the weakest device in dBm. Nearer 0 is better; "
            "below -70 is poor."
        ),
    )
    extender_status: str = Field(
        default="",
        description=(
            "Health of the Wi-Fi booster: online, flapping, offline, or none if "
            "there isn't one."
        ),
    )


class NetStatusOut(BaseModel):
    """Flat current state, for confirming recovery after an action."""

    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = Field(
        default="", description="Internal subscriber id. Never read it aloud."
    )
    healthy: bool = Field(
        default=False,
        description="True when no fault is detected. Use this to confirm the fix worked.",
    )
    fault_type: str = Field(
        default="", description="The remaining fault, or none when healthy."
    )
    wan_ok: bool = Field(
        default=False, description="True when the broadband line into the home is healthy."
    )
    wan_status: str = Field(
        default="", description="Line state: online, degraded or offline."
    )
    gateway_model: str = Field(
        default="", description="Model name of the customer's router/hub."
    )
    gateway_uptime_s: int = Field(
        default=0, description="Seconds since the router last restarted."
    )
    ap_total: int = Field(
        default=0, description="How many access points (hub plus boosters) are in the home."
    )
    ap_online: int = Field(default=0, description="How many of those are currently online.")
    extender_status: str = Field(
        default="", description="Health of the booster: online, flapping, offline, or none."
    )
    device_total: int = Field(
        default=0, description="How many devices are connected in the home."
    )
    devices_on_target_band: int = Field(
        default=0, description="How many devices are on the faster 5GHz band."
    )
    worst_device_label: str = Field(
        default="", description="Human name of the device with the weakest signal."
    )
    worst_device_band: str = Field(
        default="", description="Band of the weakest device: 2.4 or 5."
    )
    worst_device_rssi: int = Field(
        default=0, description="Signal of the weakest device in dBm; below -70 is poor."
    )
    coverage: str = Field(
        default="good",
        description=(
            "Whether the home has a structural coverage weakness: good or weak. This is "
            "SEPARATE from fault_type — a home can have fault_type none and still have "
            "weak coverage. A reboot or band-steer does NOT fix weak coverage; only "
            "additional equipment (a mesh point) does. Use this to recommend an upgrade "
            "as a fact, never as a fix for the current fault."
        ),
    )
    coverage_note: str = Field(
        default="",
        description=(
            "Plain-English, speakable summary of the coverage weakness, e.g. \"Two "
            "devices are hanging at the edge of the Upstairs Extender's range.\" Empty "
            "when coverage is good. Say this to explain why a mesh upgrade would help."
        ),
    )
    coverage_device_count: int = Field(
        default=0,
        description=(
            "How many devices are sitting at the edge of range. 0 when coverage is good. "
            "This does not change when a fault is fixed — it is about distance, not faults."
        ),
    )
    coverage_worst_area: str = Field(
        default="",
        description=(
            "Where the weak coverage is, e.g. \"Upstairs Extender\". Empty when coverage "
            "is good. Use it to tell the customer which part of the home needs a mesh point."
        ),
    )


class DeviceActionIn(BaseModel):
    identifier: str
    action: str = Field(description="band-steer | reboot-extender | reboot-ap")
    target: str = Field(description="device_id or ap_id, as given by net-diagnostics.")
    params: str = Field(
        default="",
        description=(
            "Optional JSON object as a string, e.g. '{\"band\":\"5\"}'. A string rather "
            "than an object because a data action contract cannot express a nested one."
        ),
    )


class DeviceActionOut(BaseModel):
    ok: bool = Field(
        description="True when the action was applied. False means nothing changed."
    )
    action: str = Field(default="", description="The verb that was run.")
    target: str = Field(default="", description="The id that was acted on.")
    result_summary: str = Field(
        default="",
        description=(
            "Plain-English description of what changed, safe to paraphrase to the "
            "customer. On failure, why it did not run."
        ),
    )
    fault_cleared: bool = Field(
        default=False,
        description=(
            "True when the fault this action targeted is now gone. If false, a fault "
            "remains — call net-diagnostics again to see what is left."
        ),
    )


class InteractionEventIn(BaseModel):
    identifier: str
    channel: str = Field(description="webmessaging | voice | sms | email | ...")
    kind: str = Field(default="inbound", description="inbound | outbound")


class InteractionEventOut(BaseModel):
    ok: bool = Field(description="True when the interaction was recorded.")
    party_id: str = Field(
        default="", description="Internal subscriber id. Never read it aloud."
    )
    stored: bool = Field(default=False, description="True when the event was persisted.")
    last_channel: str = Field(
        default="",
        description="The channel customer-context will now report for this subscriber.",
    )


class CsatIn(BaseModel):
    identifier: str
    score: int = Field(description="1–5.")
    comment: str = ""
    conversation_ref: str = ""


class CsatOut(BaseModel):
    ok: bool = Field(description="True when the satisfaction score was accepted.")
    party_id: str = Field(
        default="", description="Internal subscriber id. Never read it aloud."
    )
    stored: bool = Field(default=False, description="True when the score was persisted.")


class DeviceOut(BaseModel):
    """One device in the customer's home. The feed is a top-level array of these.

    This is the tool to call when the customer names a device ("my daughter's iPad",
    "the telly") and you need to work out which one they mean before acting.
    """

    device_id: str = Field(
        default="",
        description=(
            "Opaque id of this device. Pass it to device-action as 'target'. Never "
            "read it aloud."
        ),
    )
    label: str = Field(
        default="",
        description=(
            "The device's name in the customer's home, e.g. \"Ella's iPad\". Match "
            "this against whatever the customer calls it."
        ),
    )
    kind: str = Field(
        default="",
        description=(
            "Category of device: phone, tablet, laptop, tv. Use it when the customer "
            "names a type rather than a device, e.g. \"the tablet\"."
        ),
    )
    band: str = Field(
        default="",
        description="Wi-Fi band it is on: 2.4 (slower, longer range) or 5 (faster).",
    )
    rssi: int = Field(
        default=0,
        description="Signal strength in dBm. Nearer 0 is better; below -70 is poor.",
    )
    ap_label: str = Field(
        default="",
        description=(
            "Which hub or booster it is connected through, e.g. 'Upstairs Extender'. "
            "Useful for telling the customer where the problem is."
        ),
    )
    steer_eligible: bool = Field(
        default=False,
        description=(
            "True when this device can be moved to the faster band with a band-steer. "
            "If false, a band-steer will not help it."
        ),
    )
    status_summary: str = Field(
        default="",
        description=(
            "Short plain-English health phrase for this device, e.g. 'weak signal on "
            "the slower band'. Safe to say to the customer as-is."
        ),
    )


class OffersOut(BaseModel):
    """The single best upgrade this customer's network justifies, if any."""

    found: bool = Field(
        description="False when the identifier resolves to no subscriber with a network."
    )
    eligible: bool = Field(
        default=False,
        description=(
            "True when there is an offer worth making. When false there is no suitable "
            "upgrade — do not invent one, and do not pressure the customer."
        ),
    )
    offer_id: str = Field(
        default="",
        description="Id of the offer. Pass it to order-action 'place' as target.",
    )
    name: str = Field(
        default="", description="The offer's name, e.g. 'Northwind Mesh Pro'."
    )
    price_gbp: float = Field(
        default=0.0, description="Monthly price in pounds. Always state this before ordering."
    )
    reason: str = Field(
        default="",
        description=(
            "Why this customer specifically would benefit, in plain English. Use this "
            "to explain the recommendation rather than making up a reason."
        ),
    )


class OrderActionIn(BaseModel):
    identifier: str
    action: str = Field(description="place | send-confirmation")
    target: str = Field(
        description=(
            "For place: the offer_id from get-offers. "
            "For send-confirmation: the order_id returned by place."
        )
    )
    params: str = Field(
        default="",
        description=(
            "Optional JSON object as a string. A string rather than an object because "
            "a data action contract cannot express a nested one."
        ),
    )


class OrderActionOut(BaseModel):
    """One shape for both verbs, so a flow binds the same fields either way. The verb
    that does not produce a field leaves it empty."""

    ok: bool = Field(
        description="True when the action succeeded. False means nothing was ordered or sent."
    )
    action: str = Field(default="", description="The verb that was run.")
    order_id: str = Field(
        default="",
        description=(
            "The order's id. After 'place', pass this to 'send-confirmation' as target."
        ),
    )
    status: str = Field(
        default="",
        description="Order state: placed, confirmed or cancelled.",
    )
    eta_text: str = Field(
        default="",
        description=(
            "When the customer can expect it, in plain English. Safe to say as-is."
        ),
    )
    sent_to_masked: str = Field(
        default="",
        description=(
            "Masked address the confirmation went to, e.g. 'a••••@example.net'. Use it "
            "to confirm where it went without reciting the full address."
        ),
    )
    message_ref: str = Field(
        default="",
        description="Reference for the confirmation message, if the customer asks.",
    )
    result_summary: str = Field(
        default="",
        description=(
            "Plain-English description of what happened, safe to paraphrase. On "
            "failure, why it did not run."
        ),
    )


class TelemetryOut(BaseModel):
    """One telemetry event, flat. The feed is a top-level array of these — allowed by
    the gx rule (an array nested in a property is not; a top-level array is)."""

    party_id: str = Field(
        default="", description="Internal subscriber id the event belongs to."
    )
    kind: str = Field(default="", description="Event kind, e.g. network.degraded.")
    fault_type: str = Field(
        default="", description="The fault detected when this event was raised."
    )
    primary_target: str = Field(
        default="", description="Opaque id of the affected thing. Never read it aloud."
    )
    primary_target_kind: str = Field(
        default="", description="What the target is: device, ap, or gateway."
    )
    primary_target_label: str = Field(
        default="", description="Human name of the affected thing."
    )
    recommended_action: str = Field(
        default="", description="The verb that would remedy this fault."
    )
    conversation_ref: str = Field(
        default="", description="Genesys conversation id, when the event came from one."
    )
    occurred_at: str = Field(
        default="", description="ISO-8601 timestamp of when the event was raised."
    )
