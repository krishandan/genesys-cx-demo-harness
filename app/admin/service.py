"""Shared read model for the admin surface: what each subscriber's network looks like."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.admin.schemas import ActivityOut, SubscriberStateOut
from app.core.models import Identity, Party, Tenant
from app.events.models import KIND_CSAT, KIND_INTERACTION, KIND_NETWORK_DEGRADED, Event
from app.events.service import recent_events as recent_store_events
from app.modules.network.config import network_config
from app.modules.network.faults import NO_FAULT, build_verdict
from app.modules.network.service import load_topology


def subscriber_states(db: Session, tenant: Tenant) -> list[SubscriberStateOut]:
    """Every subscriber for the tenant, with the same verdict gx would report."""
    parties = (
        db.execute(
            select(Party)
            .where(Party.tenant_id == tenant.tenant_id)
            .options(selectinload(Party.identities))
            .order_by(Party.display_name)
        )
        .scalars()
        .all()
    )

    cfg = network_config(tenant)
    states = []

    for party in parties:
        primary = next(
            (i for i in party.identities if i.is_primary),
            party.identities[0] if party.identities else None,
        )
        topology = load_topology(db, tenant, party.party_id)

        if topology.is_empty:
            states.append(
                SubscriberStateOut(
                    party_id=str(party.party_id),
                    display_name=party.display_name,
                    identifier=primary.value if primary else "",
                    tier=party.tier or "",
                    has_network=False,
                    healthy=False,
                    fault_type="",
                    recommended_action="",
                    wan_status="",
                    extender_status="",
                    worst_device_label="",
                    worst_device_band="",
                    worst_device_rssi=0,
                )
            )
            continue

        verdict = build_verdict(topology, cfg)
        worst = min(topology.devices, key=lambda d: d.rssi) if topology.devices else None

        states.append(
            SubscriberStateOut(
                party_id=str(party.party_id),
                display_name=party.display_name,
                identifier=primary.value if primary else "",
                tier=party.tier or "",
                has_network=True,
                healthy=verdict.fault_type == NO_FAULT,
                fault_type=verdict.fault_type,
                recommended_action=verdict.recommended_action,
                wan_status=topology.gateway.wan_status if topology.gateway else "",
                extender_status=verdict.extender_status,
                worst_device_label=worst.label if worst else "",
                worst_device_band=worst.band if worst else "",
                worst_device_rssi=worst.rssi if worst else 0,
            )
        )

    return states


def identity_count(db: Session, tenant: Tenant) -> int:
    return len(
        db.execute(select(Identity.identity_id).where(Identity.tenant_id == tenant.tenant_id))
        .scalars()
        .all()
    )


def _activity_summary(event: Event) -> str:
    payload = event.payload or {}
    if event.kind == KIND_INTERACTION:
        return f"{payload.get('kind', 'interaction')} on {event.channel}"
    if event.kind == KIND_CSAT:
        comment = payload.get("comment", "")
        base = f"score {payload.get('score', '?')}/5"
        return f"{base} — “{comment}”" if comment else base
    if event.kind == KIND_NETWORK_DEGRADED:
        return f"{payload.get('fault_type', 'fault')} → {payload.get('recommended_action', '')}"
    return event.kind


def activity_feed(db: Session, tenant: Tenant, limit: int = 30) -> list[ActivityOut]:
    """Interaction, CSAT and telemetry events for the admin feed, newest first."""
    return [
        ActivityOut(
            kind=e.kind,
            channel=e.channel,
            conversation_ref=e.conversation_ref,
            summary=_activity_summary(e),
            occurred_at=e.occurred_at,
        )
        for e in recent_store_events(db, tenant, limit=limit)
    ]
