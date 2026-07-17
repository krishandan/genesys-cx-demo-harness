"""Topology loading. The rich graph lives here; gx never sees it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.models import Tenant
from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway, Radio


@dataclass(frozen=True)
class Topology:
    """One subscriber's home network."""

    party_id: uuid.UUID
    gateway: Gateway | None
    access_points: list[AccessPoint]
    devices: list[ConnectedDevice]

    @property
    def extenders(self) -> list[AccessPoint]:
        return [ap for ap in self.access_points if ap.kind == "extender"]

    def ap_by_id(self, ap_id: uuid.UUID) -> AccessPoint | None:
        return next((ap for ap in self.access_points if ap.ap_id == ap_id), None)

    def bands_on(self, ap_id: uuid.UUID) -> set[str]:
        ap = self.ap_by_id(ap_id)
        return {r.band for r in ap.radios} if ap else set()

    @property
    def is_empty(self) -> bool:
        return self.gateway is None and not self.access_points and not self.devices


def load_topology(db: Session, tenant: Tenant, party_id: uuid.UUID) -> Topology:
    """Load a subscriber's network. Tenant-scoped on every table."""
    gateway = db.execute(
        select(Gateway).where(
            Gateway.tenant_id == tenant.tenant_id, Gateway.party_id == party_id
        )
    ).scalar_one_or_none()

    access_points = list(
        db.execute(
            select(AccessPoint)
            .where(
                AccessPoint.tenant_id == tenant.tenant_id,
                AccessPoint.party_id == party_id,
            )
            .options(selectinload(AccessPoint.radios))
            .order_by(AccessPoint.kind, AccessPoint.label)
        )
        .scalars()
        .all()
    )

    devices = list(
        db.execute(
            select(ConnectedDevice)
            .where(
                ConnectedDevice.tenant_id == tenant.tenant_id,
                ConnectedDevice.party_id == party_id,
            )
            .order_by(ConnectedDevice.label)
        )
        .scalars()
        .all()
    )

    return Topology(
        party_id=party_id, gateway=gateway, access_points=access_points, devices=devices
    )


def radios_for(db: Session, tenant: Tenant, party_id: uuid.UUID) -> list[Radio]:
    return list(
        db.execute(
            select(Radio)
            .where(Radio.tenant_id == tenant.tenant_id, Radio.party_id == party_id)
            .order_by(Radio.band)
        )
        .scalars()
        .all()
    )
