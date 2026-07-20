"""Order persistence. Tenant- and party-scoped on every read and write."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.modules.offers.service import Offer
from app.modules.orders.models import (
    LIVE_STATUSES,
    STATUS_CONFIRMED,
    STATUS_PLACED,
    CustomerOrder,
)


def find_live_order(
    db: Session, tenant: Tenant, party_id: uuid.UUID, offer_id: str
) -> CustomerOrder | None:
    """An existing, non-cancelled order for this subscriber and offer.

    This is what makes `place` idempotent: asking twice for the same offer returns the
    order that already exists rather than creating a second one.
    """
    return db.execute(
        select(CustomerOrder).where(
            CustomerOrder.tenant_id == tenant.tenant_id,
            CustomerOrder.party_id == party_id,
            CustomerOrder.offer_id == offer_id,
            CustomerOrder.status.in_(LIVE_STATUSES),
        )
    ).scalar_one_or_none()


def get_order(
    db: Session, tenant: Tenant, party_id: uuid.UUID, order_id: str
) -> CustomerOrder | None:
    """Look an order up by id, scoped to the subscriber who owns it."""
    try:
        parsed = uuid.UUID(order_id)
    except (ValueError, AttributeError):
        return None

    return db.execute(
        select(CustomerOrder).where(
            CustomerOrder.tenant_id == tenant.tenant_id,
            CustomerOrder.party_id == party_id,
            CustomerOrder.order_id == parsed,
        )
    ).scalar_one_or_none()


def place_order(
    db: Session, tenant: Tenant, party_id: uuid.UUID, offer: Offer
) -> tuple[CustomerOrder, bool]:
    """Return (order, created). Existing live order wins, so this is idempotent."""
    existing = find_live_order(db, tenant, party_id, offer.offer_id)
    if existing is not None:
        return existing, False

    order = CustomerOrder(
        tenant_id=tenant.tenant_id,
        party_id=party_id,
        offer_id=offer.offer_id,
        offer_name=offer.name,
        price_gbp=Decimal(str(offer.price_gbp)),
        status=STATUS_PLACED,
        eta_text=offer.eta_text,
    )
    db.add(order)
    db.flush()
    return order, True


def message_ref_for(order: CustomerOrder) -> str:
    """Deterministic per order, so a repeated confirmation reports the same reference."""
    return f"MSG-{str(order.order_id)[:8].upper()}"


def mark_confirmed(db: Session, order: CustomerOrder) -> str:
    """Record that a confirmation went out. Idempotent: the first ref sticks."""
    if order.confirmation_message_ref:
        return order.confirmation_message_ref

    order.confirmation_message_ref = message_ref_for(order)
    order.confirmed_at = datetime.now(UTC)
    order.status = STATUS_CONFIRMED
    db.add(order)
    db.flush()
    return order.confirmation_message_ref


def party_orders(db: Session, tenant: Tenant, party_id: uuid.UUID) -> list[CustomerOrder]:
    return list(
        db.execute(
            select(CustomerOrder)
            .where(
                CustomerOrder.tenant_id == tenant.tenant_id,
                CustomerOrder.party_id == party_id,
            )
            .order_by(CustomerOrder.created_at.desc())
        )
        .scalars()
        .all()
    )
