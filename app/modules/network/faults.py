"""Fault detection: turn a topology into the flat verdict AVA needs.

Each fault is a detector registered by name. Adding a fault type means adding a detector
and naming it in `fault_precedence` config — not rewriting this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.modules.network.models import AccessPoint, ConnectedDevice
from app.modules.network.service import Topology

NO_FAULT = "none"

# Worst first. Used to collapse several extenders into one flat status field.
_AP_SEVERITY = {"offline": 2, "flapping": 1, "online": 0}


@dataclass(frozen=True)
class Finding:
    """A fault that fired, and the thing to act on."""

    fault_type: str
    target: str
    target_kind: str
    target_label: str


@dataclass(frozen=True)
class Verdict:
    """The flat decision. Mirrors the gx response one-for-one."""

    fault_type: str
    primary_target: str
    primary_target_kind: str
    primary_target_label: str
    recommended_action: str
    wan_ok: bool
    worst_device_band: str
    worst_device_rssi: int
    extender_status: str


Detector = Callable[[Topology, dict[str, Any]], Finding | None]

DETECTORS: dict[str, Detector] = {}


def detector(name: str) -> Callable[[Detector], Detector]:
    def register(fn: Detector) -> Detector:
        DETECTORS[name] = fn
        return fn

    return register


@detector("wan_degraded")
def _wan_degraded(topology: Topology, cfg: dict[str, Any]) -> Finding | None:
    gateway = topology.gateway
    if gateway is None or gateway.wan_status in cfg["wan_ok_statuses"]:
        return None
    return Finding(
        fault_type="wan_degraded",
        target=str(gateway.gateway_id),
        target_kind="gateway",
        target_label=gateway.model,
    )


def _stuck_devices(topology: Topology, cfg: dict[str, Any]) -> list[ConnectedDevice]:
    target_band = cfg["steer_target_band"]
    poor = cfg["poor_rssi_dbm"]
    return [
        d
        for d in topology.devices
        if d.steer_eligible
        and d.band != target_band
        and d.rssi <= poor
        # Only stuck if there is somewhere better to go.
        and target_band in topology.bands_on(d.connected_ap_id)
    ]


@detector("device_band_stuck")
def _device_band_stuck(topology: Topology, cfg: dict[str, Any]) -> Finding | None:
    stuck = _stuck_devices(topology, cfg)
    if not stuck:
        return None
    worst = min(stuck, key=lambda d: d.rssi)
    return Finding(
        fault_type="device_band_stuck",
        target=str(worst.device_id),
        target_kind="device",
        target_label=worst.label,
    )


def _unhealthy_extenders(topology: Topology, cfg: dict[str, Any]) -> list[AccessPoint]:
    return [
        ap
        for ap in topology.extenders
        if ap.status in cfg["flapping_ap_statuses"]
        or ap.backhaul_quality <= cfg["poor_backhaul_quality"]
    ]


@detector("extender_flapping")
def _extender_flapping(topology: Topology, cfg: dict[str, Any]) -> Finding | None:
    bad = _unhealthy_extenders(topology, cfg)
    if not bad:
        return None
    worst = min(bad, key=lambda ap: ap.backhaul_quality)
    return Finding(
        fault_type="extender_flapping",
        target=str(worst.ap_id),
        target_kind="ap",
        target_label=worst.label,
    )


def detect_all(topology: Topology, cfg: dict[str, Any]) -> dict[str, Finding]:
    """Every fault currently firing, keyed by fault_type."""
    findings = {}
    for name, detect in DETECTORS.items():
        finding = detect(topology, cfg)
        if finding is not None:
            findings[name] = finding
    return findings


def _extender_status(topology: Topology) -> str:
    if not topology.extenders:
        return "none"
    worst = max(topology.extenders, key=lambda ap: _AP_SEVERITY.get(ap.status, 0))
    return worst.status


def build_verdict(topology: Topology, cfg: dict[str, Any]) -> Verdict:
    """Pick the fault to act on, by configured precedence."""
    findings = detect_all(topology, cfg)

    chosen: Finding | None = None
    for name in cfg["fault_precedence"]:
        if name in findings:
            chosen = findings[name]
            break

    fault_type = chosen.fault_type if chosen else NO_FAULT
    worst_device = min(topology.devices, key=lambda d: d.rssi) if topology.devices else None
    wan_ok = topology.gateway is not None and topology.gateway.wan_status in cfg["wan_ok_statuses"]

    return Verdict(
        fault_type=fault_type,
        primary_target=chosen.target if chosen else "",
        primary_target_kind=chosen.target_kind if chosen else "",
        primary_target_label=chosen.target_label if chosen else "",
        recommended_action=cfg["recommended_actions"].get(fault_type, "none"),
        wan_ok=wan_ok,
        worst_device_band=worst_device.band if worst_device else "",
        worst_device_rssi=worst_device.rssi if worst_device else 0,
        extender_status=_extender_status(topology),
    )
