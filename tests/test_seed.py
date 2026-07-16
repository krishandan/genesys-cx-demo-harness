from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.hashing import hash_factor
from app.core.models import ContactPoint, Identity, Party, Tenant, Verification
from app.seed.generator import load_pack, seed_tenant


def _count(db: Session, model: type) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_creates_expected_counts(db: Session) -> None:
    result = seed_tenant(db, "northwind")

    assert result.tenants == 1
    assert result.parties == 10
    assert _count(db, Tenant) == 1
    assert _count(db, Party) == 10
    # One verification factor per party, per the brief.
    assert _count(db, Verification) == 10
    # The pack asks for three identity types per party.
    assert _count(db, Identity) == 30


def test_seed_tenant_identity_comes_from_the_pack(db: Session) -> None:
    seed_tenant(db, "northwind")

    tenant = db.execute(select(Tenant).where(Tenant.slug == "northwind")).scalar_one()
    assert tenant.display_name == "Northwind Mobile"
    assert tenant.industry == "telco"
    assert tenant.branding_json["logo_text"] == "Northwind Mobile"
    # Behavioural config the gx layer reads, also a pack value.
    assert tenant.config_json["country"] == "GB"
    assert tenant.config_json["masked_name"]["reveal_chars"] == 1


def test_seed_is_idempotent(db: Session) -> None:
    seed_tenant(db, "northwind")
    first = {
        "tenants": _count(db, Tenant),
        "parties": _count(db, Party),
        "identities": _count(db, Identity),
        "verifications": _count(db, Verification),
        "contacts": _count(db, ContactPoint),
    }

    seed_tenant(db, "northwind")
    second = {
        "tenants": _count(db, Tenant),
        "parties": _count(db, Party),
        "identities": _count(db, Identity),
        "verifications": _count(db, Verification),
        "contacts": _count(db, ContactPoint),
    }

    assert first == second


def _write_pack(root: Path, slug: str, pack: dict) -> Path:
    (root / slug).mkdir(parents=True, exist_ok=True)
    (root / slug / "pack.yaml").write_text(yaml.safe_dump(pack))
    return root


def test_editing_a_pack_does_not_strand_old_rows(db: Session, tmp_path: Path) -> None:
    """The seed is authoritative for its tenant.

    Row keys are uuid5 digests of natural keys, so changing a pack value mints new keys.
    Without pruning, the superseded rows would survive alongside the new ones.
    """
    pack = {
        "tenant": {"slug": "driftco", "display_name": "Drift Co", "industry": "telco"},
        "seed": {
            "faker_seed": 7,
            "faker_locale": "en_GB",
            "party_count": 3,
            "tiers": ["bronze"],
            "identities": ["phone"],
            "verification": {"factor_type": "dob", "value_pattern": "1990-01-0{index}"},
            "contact_channels": ["sms"],
            "phone_pattern": "+447700902{index:03d}",
            "email_domain": "example.net",
            "account_pattern": "DC{index:06d}",
        },
    }
    _write_pack(tmp_path, "driftco", pack)
    seed_tenant(db, "driftco", packs_dir=tmp_path)

    assert _count(db, Verification) == 3

    # Now the pack changes its factor, exactly as northwind did in BE-1.
    pack["seed"]["verification"] = {"factor_type": "pin", "value_pattern": "1234"}
    _write_pack(tmp_path, "driftco", pack)
    seed_tenant(db, "driftco", packs_dir=tmp_path)

    factors = db.execute(select(Verification)).scalars().all()
    assert len(factors) == 3, "old dob rows were stranded alongside the new pin rows"
    assert {f.factor_type for f in factors} == {"pin"}


def test_shrinking_a_pack_removes_the_extra_parties(db: Session, tmp_path: Path) -> None:
    pack = {
        "tenant": {"slug": "shrinkco", "display_name": "Shrink Co", "industry": "telco"},
        "seed": {
            "faker_seed": 7,
            "faker_locale": "en_GB",
            "party_count": 5,
            "tiers": ["bronze"],
            "identities": ["phone"],
            "verification": {"factor_type": "pin", "value_pattern": "1234"},
            "contact_channels": ["sms"],
            "phone_pattern": "+447700903{index:03d}",
            "email_domain": "example.net",
            "account_pattern": "SC{index:06d}",
        },
    }
    _write_pack(tmp_path, "shrinkco", pack)
    seed_tenant(db, "shrinkco", packs_dir=tmp_path)
    assert _count(db, Party) == 5

    pack["seed"]["party_count"] = 2
    _write_pack(tmp_path, "shrinkco", pack)
    seed_tenant(db, "shrinkco", packs_dir=tmp_path)

    assert _count(db, Party) == 2
    assert _count(db, Identity) == 2


def test_pruning_one_tenant_does_not_touch_another(
    db: Session, tmp_path: Path, seeded_northwind: None
) -> None:
    """A re-seed must never reach outside its own tenant."""
    before = _count(db, Party)

    pack = {
        "tenant": {"slug": "otherco", "display_name": "Other Co", "industry": "telco"},
        "seed": {
            "faker_seed": 7,
            "faker_locale": "en_GB",
            "party_count": 2,
            "tiers": ["bronze"],
            "identities": ["phone"],
            "verification": {"factor_type": "pin", "value_pattern": "1234"},
            "contact_channels": ["sms"],
            "phone_pattern": "+447700904{index:03d}",
            "email_domain": "example.net",
            "account_pattern": "OC{index:06d}",
        },
    }
    _write_pack(tmp_path, "otherco", pack)
    seed_tenant(db, "otherco", packs_dir=tmp_path)

    # northwind's 10 parties are untouched; otherco added 2.
    assert _count(db, Party) == before + 2


def test_seed_is_deterministic(db: Session) -> None:
    seed_tenant(db, "northwind")
    names_first = db.execute(select(Party.display_name).order_by(Party.party_id)).scalars().all()

    seed_tenant(db, "northwind")
    names_second = db.execute(select(Party.display_name).order_by(Party.party_id)).scalars().all()

    assert names_first == names_second


def test_verification_factors_are_hashed_not_plaintext(db: Session) -> None:
    seed_tenant(db, "northwind")

    pack = load_pack("northwind")
    configured = pack["seed"]["verification"]
    plaintext = configured["value_pattern"].format(index=0)

    factors = db.execute(select(Verification)).scalars().all()
    assert factors
    for factor in factors:
        # The factor type is pack config, not a literal in code.
        assert factor.factor_type == configured["factor_type"]
        assert len(factor.value_hash) == 64  # sha256 hex digest
        assert plaintext not in factor.value_hash

    # And the stored digest is the one gx verify-customer will recompute.
    expected = hash_factor(configured["factor_type"], plaintext)
    assert any(f.value_hash == expected for f in factors)
