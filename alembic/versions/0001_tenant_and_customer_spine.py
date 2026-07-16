"""Tenant + Customer Spine

Revision ID: 0001
Revises:
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("industry", sa.String(length=64), nullable=False),
        sa.Column("branding_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_tenant_slug"), "tenant", ["slug"])

    op.create_table(
        "party",
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_type", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("party_id"),
        sa.CheckConstraint("party_type IN ('person', 'org')", name="ck_party_party_type"),
    )
    op.create_index(op.f("ix_party_tenant_id"), "party", ["tenant_id"])

    op.create_table(
        "identity",
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("identity_id"),
        sa.UniqueConstraint("tenant_id", "id_type", "value", name="uq_identity_tenant_type_value"),
        sa.CheckConstraint(
            "id_type IN ('phone', 'email', 'account_no', 'msisdn')",
            name="ck_identity_id_type",
        ),
    )
    op.create_index(op.f("ix_identity_tenant_id"), "identity", ["tenant_id"])
    op.create_index(op.f("ix_identity_party_id"), "identity", ["party_id"])
    op.create_index(op.f("ix_identity_value"), "identity", ["value"])

    op.create_table(
        "verification",
        sa.Column("verification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("factor_type", sa.String(length=16), nullable=False),
        sa.Column("value_hash", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("verification_id"),
        sa.CheckConstraint(
            "factor_type IN ('dob', 'zip', 'pin', 'last4')",
            name="ck_verification_factor_type",
        ),
    )
    op.create_index(op.f("ix_verification_party_id"), "verification", ["party_id"])

    op.create_table(
        "contact_point",
        sa.Column("contact_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["party.party_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_point_id"),
    )
    op.create_index(op.f("ix_contact_point_party_id"), "contact_point", ["party_id"])


def downgrade() -> None:
    op.drop_table("contact_point")
    op.drop_table("verification")
    op.drop_table("identity")
    op.drop_table("party")
    op.drop_table("tenant")
