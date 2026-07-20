"""Device kind + customer orders

`kind` lets the agent match a device the customer *names* ("my daughter's iPad") by
category as well as label, and is pack config rather than derived from the label.

The order table is named `customer_order` because `order` is a reserved word in SQL.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "connected_device",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=""),
    )

    op.create_table(
        "customer_order",
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False),
        # The offer's name and price are snapshotted at purchase: the pack catalogue
        # may change, but what the customer bought must not.
        sa.Column("offer_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("price_gbp", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="placed"),
        sa.Column("eta_text", sa.String(length=128), nullable=False, server_default=""),
        # Set once a confirmation goes out; its presence is what makes
        # send-confirmation idempotent.
        sa.Column(
            "confirmation_message_ref", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("order_id"),
        sa.CheckConstraint(
            "status IN ('placed', 'confirmed', 'cancelled')", name="ck_customer_order_status"
        ),
    )
    op.create_index(op.f("ix_customer_order_tenant_id"), "customer_order", ["tenant_id"])
    op.create_index(op.f("ix_customer_order_party_id"), "customer_order", ["party_id"])
    # One live order per subscriber per offer is what makes `place` idempotent.
    op.create_index(
        "ix_customer_order_party_offer", "customer_order", ["party_id", "offer_id"]
    )


def downgrade() -> None:
    op.drop_table("customer_order")
    op.drop_column("connected_device", "kind")
