"""Tenant + Customer Spine.

Generic by design: nothing here knows about telco, banking, or insurance. An industry
is a seed pack, not a column. Allowed values for the typed columns are held as CHECK
constraints so the vocabulary is visible in the schema rather than in application code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PARTY_TYPES = ("person", "org")
ID_TYPES = ("phone", "email", "account_no", "msisdn")
FACTOR_TYPES = ("dob", "zip", "pin", "last4")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base):
    """A Genesys customer: a telco, a bank, an insurer."""

    __tablename__ = "tenant"

    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    branding_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Behavioural tenant config (country, masked_name format, ...). Deliberately a
    # JSONB bag: new tenant config is a pack edit, not a migration.
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    parties: Mapped[list[Party]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class Party(Base):
    """A subscriber / end customer of a tenant: the person who messages in."""

    __tablename__ = "party"
    __table_args__ = (
        CheckConstraint(
            "party_type IN ('person', 'org')",
            name="ck_party_party_type",
        ),
    )

    party_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_type: Mapped[str] = mapped_column(String(16), nullable=False, default="person")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="parties")
    identities: Mapped[list[Identity]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )
    verifications: Mapped[list[Verification]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )
    contact_points: Mapped[list[ContactPoint]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )


class Identity(Base):
    """The resolution key for a Genesys ANI / email / account lookup.

    tenant_id is carried here (not only on party) so uniqueness can be enforced per
    tenant: two tenants may legitimately hold the same phone number.
    """

    __tablename__ = "identity"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id_type", "value", name="uq_identity_tenant_type_value"),
        CheckConstraint(
            "id_type IN ('phone', 'email', 'account_no', 'msisdn')",
            name="ck_identity_id_type",
        ),
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    id_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    party: Mapped[Party] = relationship(back_populates="identities")


class Verification(Base):
    """A factor confirmed during verify-then-context. Never stores plaintext."""

    __tablename__ = "verification"
    __table_args__ = (
        CheckConstraint(
            "factor_type IN ('dob', 'zip', 'pin', 'last4')",
            name="ck_verification_factor_type",
        ),
    )

    verification_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    factor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    party: Mapped[Party] = relationship(back_populates="verifications")


class ContactPoint(Base):
    """A reachable channel for a party, with consent."""

    __tablename__ = "contact_point"

    contact_point_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    party: Mapped[Party] = relationship(back_populates="contact_points")
