"""Pack-driven, deterministic, idempotent seeding.

Determinism comes from two places: Faker runs off a fixed seed held in the pack, and
every primary key is a uuid5 derived from the tenant slug and the row's natural key.
Re-running therefore merges onto the same rows instead of duplicating them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from faker import Faker
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.hashing import hash_factor
from app.core.models import ContactPoint, Identity, Party, Tenant, Verification

PACKS_DIR = Path(__file__).parent / "packs"

# Fixed namespace so uuid5 keys are stable across machines and runs.
BACKLOT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


class PackNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class SeedResult:
    tenant_slug: str
    tenants: int
    parties: int
    identities: int
    verifications: int
    contact_points: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant_slug,
            "tenants": self.tenants,
            "parties": self.parties,
            "identities": self.identities,
            "verifications": self.verifications,
            "contact_points": self.contact_points,
        }


def load_pack(tenant_slug: str, packs_dir: Path = PACKS_DIR) -> dict[str, Any]:
    pack_path = packs_dir / tenant_slug / "pack.yaml"
    if not pack_path.exists():
        raise PackNotFoundError(
            f"No seed pack for tenant '{tenant_slug}' at {pack_path}. "
            f"Add a pack directory rather than editing code."
        )
    with pack_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def _key(*parts: str) -> uuid.UUID:
    return uuid.uuid5(BACKLOT_NAMESPACE, ":".join(parts))


def _email_for(name: str, index: int, domain: str) -> str:
    local = name.lower().replace(" ", ".").replace("'", "")
    return f"{local}.{index}@{domain}"


@dataclass
class _Written:
    """Primary keys this run produced, per table."""

    parties: set[uuid.UUID]
    identities: set[uuid.UUID]
    verifications: set[uuid.UUID]
    contact_points: set[uuid.UUID]


def _prune(db: Session, tenant_id: uuid.UUID, written: _Written) -> None:
    """Delete rows this tenant's pack no longer defines.

    Merging alone is not enough. Row keys are uuid5 digests of natural keys, so editing
    a pack (say, a verification factor from dob to pin) mints new keys and strands the
    old rows instead of replacing them. The seed is authoritative for its own tenant:
    what the pack does not describe should not survive a re-seed.
    """
    party_ids = select(Party.party_id).where(Party.tenant_id == tenant_id)

    db.execute(
        delete(Verification).where(
            Verification.party_id.in_(party_ids),
            Verification.verification_id.notin_(written.verifications),
        )
    )
    db.execute(
        delete(ContactPoint).where(
            ContactPoint.party_id.in_(party_ids),
            ContactPoint.contact_point_id.notin_(written.contact_points),
        )
    )
    db.execute(
        delete(Identity).where(
            Identity.tenant_id == tenant_id,
            Identity.identity_id.notin_(written.identities),
        )
    )
    db.execute(
        delete(Party).where(
            Party.tenant_id == tenant_id,
            Party.party_id.notin_(written.parties),
        )
    )


def seed_tenant(db: Session, tenant_slug: str, packs_dir: Path = PACKS_DIR) -> SeedResult:
    """Seed one tenant and its parties from that tenant's pack. Idempotent."""
    pack = load_pack(tenant_slug, packs_dir)
    tenant_cfg = pack["tenant"]
    seed_cfg = pack["seed"]

    slug = tenant_cfg["slug"]
    fake = Faker(seed_cfg.get("faker_locale", "en_GB"))
    Faker.seed(seed_cfg["faker_seed"])

    tenant_id = _key("tenant", slug)
    db.merge(
        Tenant(
            tenant_id=tenant_id,
            slug=slug,
            display_name=tenant_cfg["display_name"],
            industry=tenant_cfg["industry"],
            branding_json=tenant_cfg.get("branding_json", {}),
            config_json=tenant_cfg.get("config_json", {}),
        )
    )

    tiers: list[str] = seed_cfg["tiers"]
    id_types: list[str] = seed_cfg["identities"]
    channels: list[str] = seed_cfg["contact_channels"]
    factor_cfg: dict[str, Any] = seed_cfg["verification"]
    factor_type: str = factor_cfg["factor_type"]

    identities = verifications = contact_points = 0
    party_count = int(seed_cfg["party_count"])
    written = _Written(parties=set(), identities=set(), verifications=set(), contact_points=set())

    for i in range(party_count):
        name = fake.name()
        party_id = _key(slug, "party", str(i))
        written.parties.add(party_id)

        db.merge(
            Party(
                party_id=party_id,
                tenant_id=tenant_id,
                party_type=seed_cfg.get("party_type", "person"),
                display_name=name,
                tier=tiers[i % len(tiers)],
            )
        )

        values = {
            "phone": seed_cfg["phone_pattern"].format(index=i),
            "msisdn": seed_cfg["phone_pattern"].format(index=i),
            "email": _email_for(name, i, seed_cfg["email_domain"]),
            "account_no": seed_cfg["account_pattern"].format(index=i),
        }

        for id_type in id_types:
            identity_id = _key(slug, "party", str(i), "identity", id_type)
            written.identities.add(identity_id)
            db.merge(
                Identity(
                    identity_id=identity_id,
                    tenant_id=tenant_id,
                    party_id=party_id,
                    id_type=id_type,
                    value=values[id_type],
                    is_primary=(id_type == id_types[0]),
                )
            )
            identities += 1

        # One verification factor per party, stored only as a digest.
        factor_value = factor_cfg["value_pattern"].format(index=i)
        verification_id = _key(slug, "party", str(i), "verification", factor_type)
        written.verifications.add(verification_id)
        db.merge(
            Verification(
                verification_id=verification_id,
                party_id=party_id,
                factor_type=factor_type,
                value_hash=hash_factor(factor_type, factor_value),
            )
        )
        verifications += 1

        for channel in channels:
            contact_point_id = _key(slug, "party", str(i), "contact", channel)
            written.contact_points.add(contact_point_id)
            db.merge(
                ContactPoint(
                    contact_point_id=contact_point_id,
                    party_id=party_id,
                    channel=channel,
                    value=values["phone"] if channel == "sms" else values["email"],
                    consent=True,
                )
            )
            contact_points += 1

    db.flush()
    _prune(db, tenant_id, written)
    db.commit()

    return SeedResult(
        tenant_slug=slug,
        tenants=1,
        parties=party_count,
        identities=identities,
        verifications=verifications,
        contact_points=contact_points,
    )
