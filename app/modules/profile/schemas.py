"""Rich /v1 profile shapes. Nesting is fine here; gx is what must stay flat."""

import uuid

from pydantic import BaseModel

from app.core.schemas import ContactPointOut, IdentityOut
from app.modules.profile.service import ProfileRollup


class ProfileOut(BaseModel):
    party_id: uuid.UUID
    tenant_slug: str
    display_name: str
    party_type: str
    tier: str | None
    matched_value: str
    matched_id_type: str
    last_channel: str
    identities: list[IdentityOut]
    contact_points: list[ContactPointOut]

    @classmethod
    def from_rollup(cls, rollup: ProfileRollup) -> "ProfileOut":
        party = rollup.party
        return cls(
            party_id=party.party_id,
            tenant_slug=rollup.tenant_slug,
            display_name=party.display_name,
            party_type=party.party_type,
            tier=party.tier,
            matched_value=rollup.matched_identity.value,
            matched_id_type=rollup.matched_identity.id_type,
            last_channel=rollup.last_channel,
            identities=[IdentityOut.model_validate(i) for i in party.identities],
            contact_points=[ContactPointOut.model_validate(c) for c in party.contact_points],
        )
