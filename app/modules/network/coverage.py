"""Coverage assessment — a DURABLE, fault-independent read of the home.

A FAULT is something broken and fixable via device-action (a band-stuck device, a
flapping extender). A COVERAGE WEAKNESS is a structural property of the home: devices far
from any hub, on an extender, at the edge of its range. No repair moves a device closer,
so this signal must stay the same when a fault clears — it is true at healthy baseline,
true after band-steer, true after an extender reboot.

This is the single computation behind both `/gx/net-status` (the readout) and `/gx/offers`
(the mesh-upgrade eligibility), so the agent can state the coverage gap as a fact rather
than infer it from a raw dBm reading, and the upsell is grounded rather than a mid-problem
sales pitch. Thresholds are pack config (`config_json.network.coverage`), never constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.network.models import ConnectedDevice
from app.modules.network.service import Topology

_NUMBER_WORDS = {
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
}

GOOD = "good"
WEAK = "weak"


@dataclass(frozen=True)
class CoverageAssessment:
    """Flat, agent-speakable coverage read. Consumed by net-status and offers."""

    level: str  # "good" | "weak"
    note: str  # plain-English summary; empty when good
    device_count: int  # devices at the edge of range; 0 when good
    worst_area: str  # ap_label of the weak cluster; empty when good

    @property
    def is_weak(self) -> bool:
        return self.level == WEAK


def _count_word(n: int) -> str:
    return _NUMBER_WORDS.get(n, str(n))


def _is_edge(device: ConnectedDevice, target_band: str, edge_5: int, edge_24: int) -> bool:
    """A device at the edge of its band's range (weaker signal = more negative rssi)."""
    threshold = edge_5 if device.band == target_band else edge_24
    return device.rssi < threshold


def assess_coverage(topology: Topology, cfg: dict[str, Any]) -> CoverageAssessment:
    """The one coverage computation. Reads only distance/range, never fault state."""
    ccfg = cfg["coverage"]
    edge_5 = int(ccfg["edge_rssi_5ghz_dbm"])
    edge_24 = int(ccfg["edge_rssi_24ghz_dbm"])
    min_cluster = int(ccfg["min_cluster_size"])
    single_worst = int(ccfg["single_worst_rssi_dbm"])
    target_band = str(cfg["steer_target_band"])

    extender_ids = {ap.ap_id for ap in topology.extenders}
    labels = {ap.ap_id: ap.label for ap in topology.extenders}

    # Group the devices hanging off each extender.
    on_extender: dict[Any, list[ConnectedDevice]] = {}
    for device in topology.devices:
        if device.connected_ap_id in extender_ids:
            on_extender.setdefault(device.connected_ap_id, []).append(device)

    edge_by_ext = {
        ap_id: [d for d in devices if _is_edge(d, target_band, edge_5, edge_24)]
        for ap_id, devices in on_extender.items()
    }
    edge_by_ext = {ap_id: ds for ap_id, ds in edge_by_ext.items() if ds}

    # Two independent ways to be weak: a cluster of edge devices on one extender, or a
    # single device far enough out on its own.
    cluster_hits = {ap_id: ds for ap_id, ds in edge_by_ext.items() if len(ds) >= min_cluster}
    worst_by_ext = {ap_id: min(d.rssi for d in ds) for ap_id, ds in on_extender.items()}
    single_worst_hits = {
        ap_id: rssi for ap_id, rssi in worst_by_ext.items() if rssi < single_worst
    }

    is_weak = bool(cluster_hits or single_worst_hits)
    if not is_weak:
        return CoverageAssessment(level=GOOD, note="", device_count=0, worst_area="")

    # The area driving the weakness: the biggest cluster (worst signal breaks ties), else
    # the extender carrying the single worst device.
    if cluster_hits:
        area_id = max(
            cluster_hits,
            key=lambda ap_id: (len(cluster_hits[ap_id]), -min(d.rssi for d in cluster_hits[ap_id])),
        )
    else:
        area_id = min(single_worst_hits, key=lambda ap_id: single_worst_hits[ap_id])
    worst_area = labels.get(area_id, "")

    count = sum(len(ds) for ds in edge_by_ext.values())
    if count == 0:  # weak only via the single-worst rule; report at least that device
        count = sum(1 for rssi in worst_by_ext.values() if rssi < single_worst)

    if count >= 2:
        note = f"{_count_word(count)} devices are hanging at the edge of the {worst_area}'s range."
    else:
        note = f"A device is hanging at the edge of the {worst_area}'s range."

    return CoverageAssessment(
        level=WEAK, note=note, device_count=count, worst_area=worst_area
    )
