"""Profile resolution over the Customer Spine.

Exact-match only, and tenant-scoped. Whatever Genesys sent has already been normalized
at the gx boundary before it reaches here, so this stays a faithful low-level view.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.hashing import hash_factor
from app.core.models import Identity, Party, Tenant, Verification


@dataclass(frozen=True)
class ProfileRollup:
    """The rich shape. gx flattens this; /v1 serves it whole."""

    party: Party
    matched_identity: Identity
    last_channel: str

    @property
    def tenant_slug(self) -> str:
        return self.party.tenant.slug


def _last_channel(party: Party, matched_value: str) -> str:
    """The channel this subscriber is best reached on.

    Prefers the contact point matching the identifier they presented, then any
    consented channel. True last-interaction history arrives with BE-4 events; until
    then this is derived from the spine rather than invented.
    """
    points = sorted(party.contact_points, key=lambda c: c.channel)
    for point in points:
        if point.value == matched_value:
            return point.channel
    for point in points:
        if point.consent:
            return point.channel
    return ""


def resolve_profile(db: Session, tenant: Tenant, value: str) -> ProfileRollup | None:
    """Resolve a subscriber by an exact identity value, scoped to the tenant."""
    if not value:
        return None

    identity = db.execute(
        select(Identity)
        .where(Identity.tenant_id == tenant.tenant_id, Identity.value == value)
        .options(
            selectinload(Identity.party).selectinload(Party.identities),
            selectinload(Identity.party).selectinload(Party.contact_points),
            selectinload(Identity.party).selectinload(Party.tenant),
        )
    ).scalar_one_or_none()

    if identity is None:
        return None

    return ProfileRollup(
        party=identity.party,
        matched_identity=identity,
        last_channel=_last_channel(identity.party, identity.value),
    )


def check_factor(db: Session, party: Party, factor_type: str, factor_value: str) -> bool:
    """Recompute the BE-0 digest and compare against the stored hash."""
    stored = (
        db.execute(
            select(Verification).where(
                Verification.party_id == party.party_id,
                Verification.factor_type == factor_type,
            )
        )
        .scalars()
        .all()
    )

    if not stored:
        return False

    candidate = hash_factor(factor_type, factor_value)
    return any(hmac.compare_digest(v.value_hash, candidate) for v in stored)
