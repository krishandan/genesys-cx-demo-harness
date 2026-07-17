"""Entity seed_key + scenario event log

seed_key gives every seeded network entity the stable logical name its pack used
("phone", "ext1"), so a scenario can match on it instead of on a hardcoded id or on
mutable state like band or status.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

SEEDED_TABLES = ("gateway", "access_point", "radio", "connected_device")


def upgrade() -> None:
    for table in SEEDED_TABLES:
        op.add_column(
            table,
            sa.Column("seed_key", sa.String(length=32), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{table}_seed_key", table, ["seed_key"])

    op.create_table(
        "scenario_event",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("rows_changed", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_scenario_event_tenant_id"), "scenario_event", ["tenant_id"])
    op.create_index(op.f("ix_scenario_event_created_at"), "scenario_event", ["created_at"])


def downgrade() -> None:
    op.drop_table("scenario_event")
    for table in SEEDED_TABLES:
        op.drop_index(f"ix_{table}_seed_key", table_name=table)
        op.drop_column(table, "seed_key")
