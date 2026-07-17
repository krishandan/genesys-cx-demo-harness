"""device-action verbs.

Handlers register by name, so a new verb is a function here rather than a new gx route
or a new Genesys data action. Each mutates state, so a follow-up net-status or
net-diagnostics reflects what happened.

Every failure path returns a typed outcome with a 4xx: an unknown target or an
inapplicable verb is a caller mistake, never a 500.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.network.service import Topology


@dataclass(frozen=True)
class ActionOutcome:
    ok: bool
    result_summary: str
    status_code: int = 200


Handler = Callable[[Session, Topology, str, dict[str, Any], dict[str, Any]], ActionOutcome]

ACTION_HANDLERS: dict[str, Handler] = {}


def action(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        ACTION_HANDLERS[name] = fn
        return fn

    return register


def _as_uuid(target: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(target)
    except (ValueError, AttributeError):
        return None


def _unknown_target(target: str) -> ActionOutcome:
    return ActionOutcome(
        ok=False,
        result_summary=f"No such target '{target}' for this subscriber",
        status_code=404,
    )


@action("band-steer")
def band_steer(
    db: Session,
    topology: Topology,
    target: str,
    params: dict[str, Any],
    cfg: dict[str, Any],
) -> ActionOutcome:
    """Move a steer-eligible device onto the target band and let its rssi recover."""
    device_id = _as_uuid(target)
    device = next((d for d in topology.devices if d.device_id == device_id), None)
    if device is None:
        return _unknown_target(target)

    if not device.steer_eligible:
        return ActionOutcome(
            ok=False,
            result_summary=f"{device.label} is not steer-eligible",
            status_code=400,
        )

    band = str(params.get("band") or cfg["steer_target_band"])
    if band not in topology.bands_on(device.connected_ap_id):
        return ActionOutcome(
            ok=False,
            result_summary=f"No {band}GHz radio on the access point {device.label} is using",
            status_code=400,
        )

    if device.band == band:
        return ActionOutcome(
            ok=True, result_summary=f"{device.label} is already on {band}GHz"
        )

    was_band, was_rssi = device.band, device.rssi
    device.band = band
    device.rssi = min(
        device.rssi + int(cfg["steer_rssi_gain_db"]), int(cfg["steer_rssi_ceiling_dbm"])
    )
    db.add(device)

    return ActionOutcome(
        ok=True,
        result_summary=(
            f"Moved {device.label} from {was_band}GHz to {band}GHz; "
            f"signal {was_rssi} → {device.rssi} dBm"
        ),
    )


@action("reboot-extender")
def reboot_extender(
    db: Session,
    topology: Topology,
    target: str,
    params: dict[str, Any],
    cfg: dict[str, Any],
) -> ActionOutcome:
    """Cycle an extender: it drops, comes back, and its backhaul settles."""
    ap_id = _as_uuid(target)
    ap = topology.ap_by_id(ap_id) if ap_id else None
    if ap is None:
        return _unknown_target(target)

    if ap.kind != "extender":
        return ActionOutcome(
            ok=False,
            result_summary=f"{ap.label} is a {ap.kind}, not an extender",
            status_code=400,
        )

    was_status, was_backhaul = ap.status, ap.backhaul_quality
    ap.status = "online"
    ap.backhaul_quality = int(cfg["healthy_backhaul_quality"])
    db.add(ap)

    return ActionOutcome(
        ok=True,
        result_summary=(
            f"Rebooted {ap.label}: went offline and came back {was_status} → online; "
            f"backhaul {was_backhaul} → {ap.backhaul_quality}"
        ),
    )


@action("reboot-ap")
def reboot_ap(
    db: Session,
    topology: Topology,
    target: str,
    params: dict[str, Any],
    cfg: dict[str, Any],
) -> ActionOutcome:
    """Cycle any access point. Connected devices reattach to it.

    Whether the customer's own session survives is a Genesys-side concern (GX-D offers
    to move them to mobile data first). The backend just flips it offline → online.
    """
    ap_id = _as_uuid(target)
    ap = topology.ap_by_id(ap_id) if ap_id else None
    if ap is None:
        return _unknown_target(target)

    was_status = ap.status
    ap.status = "online"
    ap.backhaul_quality = max(ap.backhaul_quality, int(cfg["healthy_backhaul_quality"]))
    db.add(ap)

    reattached = [d for d in topology.devices if d.connected_ap_id == ap.ap_id]

    return ActionOutcome(
        ok=True,
        result_summary=(
            f"Rebooted {ap.label} ({was_status} → online); "
            f"{len(reattached)} device(s) reattached"
        ),
    )


def unknown_action(name: str) -> ActionOutcome:
    known = ", ".join(sorted(ACTION_HANDLERS))
    return ActionOutcome(
        ok=False,
        result_summary=f"Unknown action '{name}'. Known actions: {known}",
        status_code=400,
    )
