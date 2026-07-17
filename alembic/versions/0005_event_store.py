"""Event store

Generic tenant/party-scoped event table: kind + JSONB payload, so a new event kind
needs no migration.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "event",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("conversation_ref", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_event_tenant_id"), "event", ["tenant_id"])
    op.create_index(op.f("ix_event_party_id"), "event", ["party_id"])
    op.create_index(op.f("ix_event_kind"), "event", ["kind"])
    op.create_index(op.f("ix_event_occurred_at"), "event", ["occurred_at"])
    # The two hot reads: "latest interaction for this party" and "telemetry for a tenant".
    op.create_index(
        "ix_event_party_kind_occurred", "event", ["party_id", "kind", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_event_party_kind_occurred", table_name="event")
    op.drop_index(op.f("ix_event_occurred_at"), table_name="event")
    op.drop_index(op.f("ix_event_kind"), table_name="event")
    op.drop_index(op.f("ix_event_party_id"), table_name="event")
    op.drop_index(op.f("ix_event_tenant_id"), table_name="event")
    op.drop_table("event")
