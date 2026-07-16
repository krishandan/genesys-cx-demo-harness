"""Pack-driven, deterministic, idempotent seeding.

Determinism comes from two places: Faker runs off a fixed seed held in the pack, and
every primary key is a uuid5 derived from the tenant slug and the row's natural key.
Re-running therefore merges onto the same rows instead of duplicating them.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faker import Faker
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
    pack_path = packs_dir / tenant_slug / "pack.json"
    if not pack_path.exists():
        raise PackNotFoundError(
            f"No seed pack for tenant '{tenant_slug}' at {pack_path}. "
            f"Add a pack directory rather than editing code."
        )
    with pack_path.open() as f:
        data: dict[str, Any] = json.load(f)
    return data


def _key(*parts: str) -> uuid.UUID:
    return uuid.uuid5(BACKLOT_NAMESPACE, ":".join(parts))


def _email_for(name: str, index: int, domain: str) -> str:
    local = name.lower().replace(" ", ".").replace("'", "")
    return f"{local}.{index}@{domain}"


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
        )
    )

    tiers: list[str] = seed_cfg["tiers"]
    id_types: list[str] = seed_cfg["identities"]
    channels: list[str] = seed_cfg["contact_channels"]
    factor_type: str = seed_cfg["verification_factor"]

    identities = verifications = contact_points = 0
    party_count = int(seed_cfg["party_count"])

    for i in range(party_count):
        name = fake.name()
        party_id = _key(slug, "party", str(i))

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
            db.merge(
                Identity(
                    identity_id=_key(slug, "party", str(i), "identity", id_type),
                    tenant_id=tenant_id,
                    party_id=party_id,
                    id_type=id_type,
                    value=values[id_type],
                    is_primary=(id_type == id_types[0]),
                )
            )
            identities += 1

        # One verification factor per party, stored only as a digest.
        factor_value = fake.date_of_birth(minimum_age=18, maximum_age=85).isoformat()
        db.merge(
            Verification(
                verification_id=_key(slug, "party", str(i), "verification", factor_type),
                party_id=party_id,
                factor_type=factor_type,
                value_hash=hash_factor(factor_type, factor_value),
            )
        )
        verifications += 1

        for channel in channels:
            db.merge(
                ContactPoint(
                    contact_point_id=_key(slug, "party", str(i), "contact", channel),
                    party_id=party_id,
                    channel=channel,
                    value=values["phone"] if channel == "sms" else values["email"],
                    consent=True,
                )
            )
            contact_points += 1

    db.commit()

    return SeedResult(
        tenant_slug=slug,
        tenants=1,
        parties=party_count,
        identities=identities,
        verifications=verifications,
        contact_points=contact_points,
    )
