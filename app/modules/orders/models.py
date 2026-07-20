"""The order row.

Named `customer_order` because `order` is a reserved word in SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STATUS_PLACED = "placed"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"

# An order in one of these states already exists for the customer, so `place` returns it
# rather than creating a second one.
LIVE_STATUSES = (STATUS_PLACED, STATUS_CONFIRMED)


class CustomerOrder(Base):
    __tablename__ = "customer_order"
    __table_args__ = (
        CheckConstraint(
            "status IN ('placed', 'confirmed', 'cancelled')", name="ck_customer_order_status"
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Snapshotted at purchase: the pack catalogue may change, what was bought may not.
    offer_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    price_gbp: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_PLACED)
    eta_text: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # Presence makes send-confirmation idempotent.
    confirmation_message_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
