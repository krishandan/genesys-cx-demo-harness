"""Network telemetry emission.

When a subscriber's network is faulted, the module raises a `network.degraded` event
into the store. This is the seam a future proactive Genesys workflow (GX-C, post-M1)
will poll; in M1 nothing consumes it — it is built and tested, not wired.

Emission is driven by the fault verdict, never by a subscriber id, so it fires for
whoever is degraded.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.events.models import KIND_NETWORK_DEGRADED
from app.events.service import record_event
from app.modules.network.config import network_config
from app.modules.network.faults import NO_FAULT, build_verdict
from app.modules.network.service import load_topology


def emit_network_telemetry(
    db: Session, tenant: Tenant, party_id: uuid.UUID, *, commit: bool = True
) -> bool:
    """Emit `network.degraded` if this subscriber currently has a fault.

    Returns True if an event was written. Healthy subscribers emit nothing, so the
    caller can apply this to every affected party and let the fault state decide.
    """
    topology = load_topology(db, tenant, party_id)
    if topology.is_empty:
        return False

    verdict = build_verdict(topology, network_config(tenant))
    if verdict.fault_type == NO_FAULT:
        return False

    record_event(
        db,
        tenant,
        party_id,
        KIND_NETWORK_DEGRADED,
        channel="telemetry",
        payload={
            "fault_type": verdict.fault_type,
            "primary_target": verdict.primary_target,
            "primary_target_kind": verdict.primary_target_kind,
            "primary_target_label": verdict.primary_target_label,
            "recommended_action": verdict.recommended_action,
            "worst_device_rssi": verdict.worst_device_rssi,
            "extender_status": verdict.extender_status,
        },
        commit=commit,
    )
    return True
