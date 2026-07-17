"""Seed home networks from pack data.

Same contract as the spine seeder: deterministic uuid5 keys, merge rather than insert,
and prune anything this tenant's pack no longer describes (the locked "Seed authority"
decision). Kept beside the spine seeder rather than inside the network module so all
seeding rules live in one place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway, Radio


@dataclass(frozen=True)
class SeedParty:
    """A party the spine seeder just wrote, and the pack index it came from."""

    index: int
    party_id: uuid.UUID
    display_name: str

    @property
    def first_name(self) -> str:
        return self.display_name.split()[0] if self.display_name else ""


@dataclass
class NetworkCounts:
    gateways: int = 0
    access_points: int = 0
    radios: int = 0
    devices: int = 0


@dataclass
class _Written:
    gateways: set[uuid.UUID] = field(default_factory=set)
    access_points: set[uuid.UUID] = field(default_factory=set)
    radios: set[uuid.UUID] = field(default_factory=set)
    devices: set[uuid.UUID] = field(default_factory=set)


def _mac_for(slug: str, party_index: int, device_key: str) -> str:
    """A deterministic, locally-administered MAC (02: prefix), so it can never collide
    with a real vendor address."""
    digest = uuid.uuid5(uuid.NAMESPACE_DNS, f"{slug}:{party_index}:{device_key}").bytes
    return ":".join(["02"] + [f"{b:02x}" for b in digest[:5]])


def _prune(db: Session, tenant_id: uuid.UUID, written: _Written) -> None:
    """Drop network rows this tenant's pack no longer describes.

    Devices and radios first: they reference access_point.
    """
    db.execute(
        delete(ConnectedDevice).where(
            ConnectedDevice.tenant_id == tenant_id,
            ConnectedDevice.device_id.notin_(written.devices),
        )
    )
    db.execute(
        delete(Radio).where(
            Radio.tenant_id == tenant_id, Radio.radio_id.notin_(written.radios)
        )
    )
    db.execute(
        delete(AccessPoint).where(
            AccessPoint.tenant_id == tenant_id,
            AccessPoint.ap_id.notin_(written.access_points),
        )
    )
    db.execute(
        delete(Gateway).where(
            Gateway.tenant_id == tenant_id, Gateway.gateway_id.notin_(written.gateways)
        )
    )


def seed_networks(
    db: Session,
    tenant_id: uuid.UUID,
    slug: str,
    parties: list[SeedParty],
    network_cfg: dict[str, Any],
    key: Any,
) -> NetworkCounts:
    """Give each assigned party the topology its profile describes.

    `key` is the spine seeder's uuid5 helper, passed in so both seeders mint keys the
    same way.
    """
    profiles: dict[str, Any] = network_cfg["profiles"]
    assign: dict[str, list[int]] = network_cfg["assign"]

    by_index = {p.index: p for p in parties}
    counts = NetworkCounts()
    written = _Written()

    for profile_name, indexes in assign.items():
        profile = profiles[profile_name]

        for index in indexes:
            party = by_index.get(index)
            if party is None:
                # The pack assigns a topology to a party it does not seed. Skip rather
                # than fail: party_count and assign can legitimately drift.
                continue

            gateway_cfg = profile["gateway"]
            gateway_id = key(slug, "party", str(index), "gateway")
            written.gateways.add(gateway_id)
            db.merge(
                Gateway(
                    gateway_id=gateway_id,
                    tenant_id=tenant_id,
                    party_id=party.party_id,
                    seed_key=gateway_cfg.get("key", "gateway"),
                    model=gateway_cfg["model"],
                    wan_status=gateway_cfg["wan_status"],
                    uptime_s=int(gateway_cfg["uptime_s"]),
                )
            )
            counts.gateways += 1

            ap_ids: dict[str, uuid.UUID] = {}
            for ap_cfg in profile["access_points"]:
                ap_id = key(slug, "party", str(index), "ap", ap_cfg["key"])
                ap_ids[ap_cfg["key"]] = ap_id
                written.access_points.add(ap_id)
                db.merge(
                    AccessPoint(
                        ap_id=ap_id,
                        tenant_id=tenant_id,
                        party_id=party.party_id,
                        seed_key=ap_cfg["key"],
                        label=ap_cfg["label"],
                        kind=ap_cfg["kind"],
                        model=ap_cfg.get("model", ""),
                        status=ap_cfg["status"],
                        backhaul_quality=int(ap_cfg["backhaul_quality"]),
                    )
                )
                counts.access_points += 1

            for radio_cfg in profile["radios"]:
                radio_id = key(
                    slug, "party", str(index), "radio", radio_cfg["ap"], radio_cfg["band"]
                )
                written.radios.add(radio_id)
                db.merge(
                    Radio(
                        radio_id=radio_id,
                        tenant_id=tenant_id,
                        party_id=party.party_id,
                        ap_id=ap_ids[radio_cfg["ap"]],
                        seed_key=f"{radio_cfg['ap']}-{radio_cfg['band']}",
                        band=str(radio_cfg["band"]),
                        channel=int(radio_cfg["channel"]),
                        utilization=int(radio_cfg["utilization"]),
                    )
                )
                counts.radios += 1

            for device_cfg in profile["devices"]:
                device_id = key(slug, "party", str(index), "device", device_cfg["key"])
                written.devices.add(device_id)
                db.merge(
                    ConnectedDevice(
                        device_id=device_id,
                        tenant_id=tenant_id,
                        party_id=party.party_id,
                        connected_ap_id=ap_ids[device_cfg["ap"]],
                        seed_key=device_cfg["key"],
                        label=device_cfg["label"].format(first_name=party.first_name),
                        mac=_mac_for(slug, index, device_cfg["key"]),
                        band=str(device_cfg["band"]),
                        rssi=int(device_cfg["rssi"]),
                        steer_eligible=bool(device_cfg["steer_eligible"]),
                    )
                )
                counts.devices += 1

    db.flush()
    _prune(db, tenant_id, written)
    return counts


def prune_all(db: Session, tenant_id: uuid.UUID) -> None:
    """Remove every network row for a tenant whose pack no longer seeds networks."""
    _prune(db, tenant_id, _Written())


def has_networks(db: Session, tenant_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(Gateway.gateway_id).where(Gateway.tenant_id == tenant_id).limit(1)
        ).scalar_one_or_none()
        is not None
    )
