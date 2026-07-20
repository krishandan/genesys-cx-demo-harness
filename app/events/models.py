"""The event store.

Deliberately schemaless in the payload: `kind` names the event and `payload` (JSONB)
carries whatever that kind needs. Adding an event kind is a new constant and a new
payload shape, not a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Event kinds. These are values, not tables — new kinds land here without a migration.
KIND_INTERACTION = "interaction"
KIND_CSAT = "csat"
KIND_NETWORK_DEGRADED = "network.degraded"
KIND_ORDER_CONFIRMATION_SENT = "order.confirmation_sent"

# Kinds the telemetry seam exposes. A proactive workflow (GX-C, post-M1) polls these.
TELEMETRY_KINDS = (KIND_NETWORK_DEGRADED,)


class Event(Base):
    """A tenant- and party-scoped event."""

    __tablename__ = "event"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    conversation_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
