"""Device views for the agent.

`/gx/devices` exists so the agent can match a device the customer *names* ("my
daughter's iPad") to something it can act on. That means every row needs a human label
and a phrase the agent can say out loud — not raw signal numbers it has to interpret.

The phrasing thresholds are the same network config the fault detectors use, so what
the agent says about a device cannot disagree with the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.network.service import Topology


@dataclass(frozen=True)
class DeviceView:
    device_id: str
    label: str
    kind: str
    band: str
    rssi: int
    ap_label: str
    steer_eligible: bool
    status_summary: str


def status_summary(band: str, rssi: int, cfg: dict[str, Any]) -> str:
    """A short, speakable health phrase for one device."""
    poor = int(cfg["poor_rssi_dbm"])
    target_band = str(cfg["steer_target_band"])
    on_slow_band = band != target_band

    if rssi <= poor and on_slow_band:
        return "weak signal on the slower band"
    if rssi <= poor:
        return "weak signal"
    if on_slow_band:
        return "connected on the slower band"
    return "good signal on the faster band"


def describe_devices(topology: Topology, cfg: dict[str, Any]) -> list[DeviceView]:
    """Every device in the home, worst signal first so the likely culprit leads."""
    ap_labels = {ap.ap_id: ap.label for ap in topology.access_points}

    views = [
        DeviceView(
            device_id=str(device.device_id),
            label=device.label,
            kind=device.kind,
            band=device.band,
            rssi=device.rssi,
            ap_label=ap_labels.get(device.connected_ap_id, ""),
            steer_eligible=device.steer_eligible,
            status_summary=status_summary(device.band, device.rssi, cfg),
        )
        for device in topology.devices
    ]

    return sorted(views, key=lambda v: v.rssi)
