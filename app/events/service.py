"""Event store operations. Tenant- and party-scoped on every read and write."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.events.models import KIND_INTERACTION, TELEMETRY_KINDS, Event


def record_event(
    db: Session,
    tenant: Tenant,
    party_id: uuid.UUID,
    kind: str,
    *,
    channel: str = "",
    conversation_ref: str = "",
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    commit: bool = True,
) -> Event:
    """Append an event. `commit=False` lets a caller batch this into its own transaction."""
    event = Event(
        tenant_id=tenant.tenant_id,
        party_id=party_id,
        kind=kind,
        channel=channel,
        conversation_ref=conversation_ref,
        payload=payload or {},
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at

    db.add(event)
    db.flush()
    if commit:
        db.commit()
    return event


def _party_events(
    db: Session,
    tenant: Tenant,
    party_id: uuid.UUID,
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.tenant_id == tenant.tenant_id, Event.party_id == party_id)
        .order_by(Event.occurred_at.desc(), Event.event_id.desc())
    )
    if kinds is not None:
        stmt = stmt.where(Event.kind.in_(kinds))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def party_events(
    db: Session,
    tenant: Tenant,
    party_id: uuid.UUID,
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Event]:
    return _party_events(db, tenant, party_id, kinds=kinds, limit=limit)


def telemetry_events(
    db: Session, tenant: Tenant, party_id: uuid.UUID, limit: int = 20
) -> list[Event]:
    return _party_events(db, tenant, party_id, kinds=TELEMETRY_KINDS, limit=limit)


def last_interaction_channel(
    db: Session, tenant: Tenant, party_id: uuid.UUID
) -> str | None:
    """The channel of the most recent recorded interaction, or None if there are none."""
    channel = db.execute(
        select(Event.channel)
        .where(
            Event.tenant_id == tenant.tenant_id,
            Event.party_id == party_id,
            Event.kind == KIND_INTERACTION,
        )
        .order_by(Event.occurred_at.desc(), Event.event_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return channel or None


def resolve_last_channel(
    db: Session, tenant: Tenant, party_id: uuid.UUID, fallback: str
) -> str:
    """Real interaction history when it exists, else the spine-derived fallback.

    This closes the BE-1 carryover: `last_channel` was derived from contact points
    because no interaction history existed. Now it prefers the real thing.
    """
    return last_interaction_channel(db, tenant, party_id) or fallback


def recent_events(
    db: Session, tenant: Tenant, limit: int = 50, kinds: tuple[str, ...] | None = None
) -> list[Event]:
    """Tenant-wide feed for the admin view, newest first."""
    stmt = (
        select(Event)
        .where(Event.tenant_id == tenant.tenant_id)
        .order_by(Event.occurred_at.desc(), Event.event_id.desc())
        .limit(limit)
    )
    if kinds is not None:
        stmt = stmt.where(Event.kind.in_(kinds))
    return list(db.execute(stmt).scalars().all())
