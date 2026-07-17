"""Rich /v1/network shapes: the nested truth gx flattens. Nesting is fine here."""

import uuid

from pydantic import BaseModel, ConfigDict

from app.modules.network.faults import Verdict
from app.modules.network.service import Topology


class RadioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    radio_id: uuid.UUID
    band: str
    channel: int
    utilization: int


class AccessPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ap_id: uuid.UUID
    label: str
    kind: str
    model: str
    status: str
    backhaul_quality: int
    radios: list[RadioOut]


class GatewayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gateway_id: uuid.UUID
    model: str
    wan_status: str
    uptime_s: int


class ConnectedDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: uuid.UUID
    label: str
    mac: str
    connected_ap_id: uuid.UUID
    band: str
    rssi: int
    steer_eligible: bool


class VerdictOut(BaseModel):
    fault_type: str
    primary_target: str
    primary_target_kind: str
    primary_target_label: str
    recommended_action: str
    wan_ok: bool
    worst_device_band: str
    worst_device_rssi: int
    extender_status: str


class NetworkOut(BaseModel):
    party_id: uuid.UUID
    tenant_slug: str
    gateway: GatewayOut | None
    access_points: list[AccessPointOut]
    devices: list[ConnectedDeviceOut]
    verdict: VerdictOut

    @classmethod
    def build(cls, topology: Topology, tenant_slug: str, verdict: Verdict) -> "NetworkOut":
        return cls(
            party_id=topology.party_id,
            tenant_slug=tenant_slug,
            gateway=GatewayOut.model_validate(topology.gateway) if topology.gateway else None,
            access_points=[AccessPointOut.model_validate(ap) for ap in topology.access_points],
            devices=[ConnectedDeviceOut.model_validate(d) for d in topology.devices],
            verdict=VerdictOut(**vars(verdict)),
        )
