from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import ContactPoint, Identity, Party, Tenant, Verification
from app.seed.generator import seed_tenant


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


def test_seed_is_deterministic(db: Session) -> None:
    seed_tenant(db, "northwind")
    names_first = db.execute(select(Party.display_name).order_by(Party.party_id)).scalars().all()

    seed_tenant(db, "northwind")
    names_second = db.execute(select(Party.display_name).order_by(Party.party_id)).scalars().all()

    assert names_first == names_second


def test_verification_factors_are_hashed_not_plaintext(db: Session) -> None:
    seed_tenant(db, "northwind")

    factors = db.execute(select(Verification)).scalars().all()
    for factor in factors:
        assert factor.factor_type == "dob"
        # sha256 hex digest, and nothing that looks like an ISO date.
        assert len(factor.value_hash) == 64
        assert "-" not in factor.value_hash
