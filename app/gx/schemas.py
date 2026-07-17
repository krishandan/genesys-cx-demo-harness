"""Flat, contract-safe gx shapes.

Every field is a scalar. No lists, no nested objects, no nulls: Genesys data action
output contracts cannot express nested arrays, and a consistent shape means a flow can
bind every field once and branch on `found` / `verified` rather than handling absent
properties.
"""

from pydantic import BaseModel, Field


class CustomerContextOut(BaseModel):
    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = Field(default="", description="Empty when not found.")
    display_name: str = ""
    tenant_slug: str = ""
    tier: str = ""
    verified: bool = Field(
        default=False,
        description="Always false here; verification is a separate verify-customer call.",
    )
    last_channel: str = ""
    id_type_resolved: str = Field(
        default="",
        description="phone | email | account_no | msisdn | unrecognized",
    )


class VerifyCustomerIn(BaseModel):
    identifier: str
    factor_type: str = Field(description="dob | zip | pin | last4")
    factor_value: str


class VerifyCustomerOut(BaseModel):
    verified: bool
    party_id: str = ""
    masked_name: str = ""


class NetDiagnosticsOut(BaseModel):
    """The flat verdict. AVA branches on fault_type and acts on primary_target — it
    never walks the topology, which is what keeps this contract-safe."""

    found: bool = Field(description="False when the identifier resolves to no subscriber.")
    party_id: str = ""
    fault_type: str = Field(
        default="",
        description="device_band_stuck | extender_flapping | wan_degraded | none",
    )
    primary_target: str = Field(default="", description="Id to pass as device-action target.")
    primary_target_kind: str = Field(default="", description="device | ap | gateway")
    primary_target_label: str = Field(
        default="", description="Human name of the target, so a flow need not look it up."
    )
    recommended_action: str = Field(
        default="",
        description=(
            "The device-action verb to call: band-steer | reboot-extender | escalate | none"
        ),
    )
    wan_ok: bool = False
    worst_device_band: str = ""
    worst_device_rssi: int = 0
    extender_status: str = Field(default="", description="online | flapping | offline | none")


class NetStatusOut(BaseModel):
    """Flat current state, for confirming recovery after an action."""

    found: bool
    party_id: str = ""
    healthy: bool = Field(default=False, description="True when no fault is detected.")
    fault_type: str = ""
    wan_ok: bool = False
    wan_status: str = ""
    gateway_model: str = ""
    gateway_uptime_s: int = 0
    ap_total: int = 0
    ap_online: int = 0
    extender_status: str = ""
    device_total: int = 0
    devices_on_target_band: int = 0
    worst_device_label: str = ""
    worst_device_band: str = ""
    worst_device_rssi: int = 0


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
    ok: bool
    action: str = ""
    target: str = ""
    result_summary: str = ""
    fault_cleared: bool = False


class InteractionEventIn(BaseModel):
    identifier: str
    channel: str = Field(description="webmessaging | voice | sms | email | ...")
    kind: str = Field(default="inbound", description="inbound | outbound")


class InteractionEventOut(BaseModel):
    ok: bool
    party_id: str = ""
    stored: bool = False
    # Echoes the channel that customer-context will now report, for convenience.
    last_channel: str = ""


class CsatIn(BaseModel):
    identifier: str
    score: int = Field(description="1–5.")
    comment: str = ""
    conversation_ref: str = ""


class CsatOut(BaseModel):
    ok: bool
    party_id: str = ""
    stored: bool = False


class TelemetryOut(BaseModel):
    """One telemetry event, flat. The feed is a top-level array of these — allowed by
    the gx rule (an array nested in a property is not; a top-level array is)."""

    party_id: str = ""
    kind: str = ""
    fault_type: str = ""
    primary_target: str = ""
    primary_target_kind: str = ""
    primary_target_label: str = ""
    recommended_action: str = ""
    conversation_ref: str = ""
    occurred_at: str = ""
