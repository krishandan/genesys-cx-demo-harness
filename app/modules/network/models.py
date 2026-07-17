"""Network & Devices entities.

Every row carries tenant_id and party_id: a subscriber's home network is tenant-scoped
like everything else, and every query filters on both.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

WAN_STATUSES = ("online", "degraded", "offline")
AP_KINDS = ("gateway", "extender", "ap")
AP_STATUSES = ("online", "flapping", "offline")
BANDS = ("2.4", "5", "6")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Gateway(Base):
    """The subscriber's WAN device. One per subscriber."""

    __tablename__ = "gateway"
    __table_args__ = (
        CheckConstraint(
            "wan_status IN ('online', 'degraded', 'offline')",
            name="ck_gateway_wan_status",
        ),
    )

    gateway_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    seed_key: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    wan_status: Mapped[str] = mapped_column(String(16), nullable=False, default="online")
    uptime_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccessPoint(Base):
    """A mesh node: the gateway's own AP, an extender, or a standalone AP."""

    __tablename__ = "access_point"
    __table_args__ = (
        CheckConstraint("kind IN ('gateway', 'extender', 'ap')", name="ck_ap_kind"),
        CheckConstraint(
            "status IN ('online', 'flapping', 'offline')",
            name="ck_ap_status",
        ),
    )

    ap_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    seed_key: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="online")
    backhaul_quality: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    radios: Mapped[list[Radio]] = relationship(
        back_populates="access_point", cascade="all, delete-orphan"
    )
    devices: Mapped[list[ConnectedDevice]] = relationship(back_populates="access_point")


class Radio(Base):
    """One band on one access point."""

    __tablename__ = "radio"
    __table_args__ = (CheckConstraint("band IN ('2.4', '5', '6')", name="ck_radio_band"),)

    radio_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    ap_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_point.ap_id", ondelete="CASCADE"), nullable=False, index=True
    )
    seed_key: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    band: Mapped[str] = mapped_column(String(8), nullable=False)
    channel: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    utilization: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    access_point: Mapped[AccessPoint] = relationship(back_populates="radios")


class ConnectedDevice(Base):
    """A client device attached to one of the subscriber's access points."""

    __tablename__ = "connected_device"
    __table_args__ = (CheckConstraint("band IN ('2.4', '5', '6')", name="ck_device_band"),)

    device_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("party.party_id", ondelete="CASCADE"), nullable=False, index=True
    )
    connected_ap_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_point.ap_id", ondelete="CASCADE"), nullable=False, index=True
    )
    seed_key: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    mac: Mapped[str] = mapped_column(String(17), nullable=False)
    band: Mapped[str] = mapped_column(String(8), nullable=False)
    rssi: Mapped[int] = mapped_column(Integer, nullable=False)
    steer_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    access_point: Mapped[AccessPoint] = relationship(back_populates="devices")
