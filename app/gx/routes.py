"""The gx surface Genesys binds to. Read + verify only; domain verbs are later phases."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.gx.masking import mask_name
from app.gx.normalize import normalize_identifier
from app.gx.schemas import CustomerContextOut, VerifyCustomerIn, VerifyCustomerOut
from app.modules.profile.service import check_factor, resolve_profile

router = APIRouter(prefix="/gx", tags=["gx"])

DbDep = Annotated[Session, Depends(get_db)]


def _country_of(tenant: Tenant) -> str | None:
    country = tenant.config_json.get("country")
    return str(country) if country else None


@router.get("/customer-context", response_model=CustomerContextOut)
def customer_context(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[
        str,
        Query(description="Raw identifier from Genesys: ANI, email, or account number."),
    ],
) -> CustomerContextOut:
    """Resolve a subscriber. Not found is a 200 with found=false so a flow can branch."""
    normalized = normalize_identifier(identifier, _country_of(tenant))

    if not normalized.recognized:
        return CustomerContextOut(
            found=False,
            tenant_slug=tenant.slug,
            id_type_resolved=normalized.id_type,
        )

    rollup = resolve_profile(db, tenant, normalized.value)
    if rollup is None:
        return CustomerContextOut(
            found=False,
            tenant_slug=tenant.slug,
            id_type_resolved=normalized.id_type,
        )

    party = rollup.party
    return CustomerContextOut(
        found=True,
        party_id=str(party.party_id),
        display_name=party.display_name,
        tenant_slug=rollup.tenant_slug,
        tier=party.tier or "",
        verified=False,
        last_channel=rollup.last_channel,
        # What actually matched in the spine, which resolves phone vs msisdn.
        id_type_resolved=rollup.matched_identity.id_type,
    )


@router.post("/verify-customer", response_model=VerifyCustomerOut)
def verify_customer(
    tenant: CurrentTenant,
    db: DbDep,
    payload: VerifyCustomerIn,
) -> VerifyCustomerOut:
    """Confirm a factor. A wrong factor is a 200 with verified=false and no detail:
    the response must not tell a caller whether the subscriber or the factor was wrong.
    """
    normalized = normalize_identifier(payload.identifier, _country_of(tenant))
    if not normalized.recognized:
        return VerifyCustomerOut(verified=False)

    rollup = resolve_profile(db, tenant, normalized.value)
    if rollup is None:
        return VerifyCustomerOut(verified=False)

    if not check_factor(db, rollup.party, payload.factor_type, payload.factor_value):
        return VerifyCustomerOut(verified=False)

    return VerifyCustomerOut(
        verified=True,
        party_id=str(rollup.party.party_id),
        masked_name=mask_name(rollup.party.display_name, tenant.config_json.get("masked_name")),
    )
