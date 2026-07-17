"""Network & Devices

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "gateway",
        sa.Column("gateway_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("wan_status", sa.String(length=16), nullable=False),
        sa.Column("uptime_s", sa.Integer(), nullable=False),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gateway_id"),
        sa.CheckConstraint(
            "wan_status IN ('online', 'degraded', 'offline')", name="ck_gateway_wan_status"
        ),
    )
    op.create_index(op.f("ix_gateway_tenant_id"), "gateway", ["tenant_id"])
    op.create_index(op.f("ix_gateway_party_id"), "gateway", ["party_id"])

    op.create_table(
        "access_point",
        sa.Column("ap_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("backhaul_quality", sa.Integer(), nullable=False),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ap_id"),
        sa.CheckConstraint("kind IN ('gateway', 'extender', 'ap')", name="ck_ap_kind"),
        sa.CheckConstraint("status IN ('online', 'flapping', 'offline')", name="ck_ap_status"),
    )
    op.create_index(op.f("ix_access_point_tenant_id"), "access_point", ["tenant_id"])
    op.create_index(op.f("ix_access_point_party_id"), "access_point", ["party_id"])

    op.create_table(
        "radio",
        sa.Column("radio_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("ap_id", UUID, nullable=False),
        sa.Column("band", sa.String(length=8), nullable=False),
        sa.Column("channel", sa.Integer(), nullable=False),
        sa.Column("utilization", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ap_id"], ["access_point.ap_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("radio_id"),
        sa.CheckConstraint("band IN ('2.4', '5', '6')", name="ck_radio_band"),
    )
    op.create_index(op.f("ix_radio_tenant_id"), "radio", ["tenant_id"])
    op.create_index(op.f("ix_radio_party_id"), "radio", ["party_id"])
    op.create_index(op.f("ix_radio_ap_id"), "radio", ["ap_id"])

    op.create_table(
        "connected_device",
        sa.Column("device_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=False),
        sa.Column("connected_ap_id", UUID, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("mac", sa.String(length=17), nullable=False),
        sa.Column("band", sa.String(length=8), nullable=False),
        sa.Column("rssi", sa.Integer(), nullable=False),
        sa.Column("steer_eligible", sa.Boolean(), nullable=False),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connected_ap_id"], ["access_point.ap_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("device_id"),
        sa.CheckConstraint("band IN ('2.4', '5', '6')", name="ck_device_band"),
    )
    op.create_index(op.f("ix_connected_device_tenant_id"), "connected_device", ["tenant_id"])
    op.create_index(op.f("ix_connected_device_party_id"), "connected_device", ["party_id"])
    op.create_index(
        op.f("ix_connected_device_connected_ap_id"), "connected_device", ["connected_ap_id"]
    )


def downgrade() -> None:
    op.drop_table("connected_device")
    op.drop_table("radio")
    op.drop_table("access_point")
    op.drop_table("gateway")
