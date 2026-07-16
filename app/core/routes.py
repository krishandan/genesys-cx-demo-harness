"""Internal /v1 reads over the spine. Proves tenant resolution and identity resolution."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.models import Identity, Party
from app.core.schemas import PartyOut, TenantOut
from app.core.tenancy import CurrentTenant
from app.db import get_db

router = APIRouter(prefix="/v1", tags=["core"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(tenant: CurrentTenant) -> list[TenantOut]:
    """The tenant in scope for this request.

    Scoped rather than global: the point of this endpoint is to prove what X-Tenant
    (or DEFAULT_TENANT) resolved to, and Backlot tenant-scopes every query.
    """
    return [TenantOut.model_validate(tenant)]


@router.get("/parties", response_model=list[PartyOut])
def list_parties(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[
        str | None,
        Query(description="Resolve by identity value: phone, email, account_no, or msisdn."),
    ] = None,
) -> list[PartyOut]:
    stmt = (
        select(Party)
        .where(Party.tenant_id == tenant.tenant_id)
        .options(selectinload(Party.identities), selectinload(Party.contact_points))
        .order_by(Party.display_name)
    )

    if identifier is not None:
        stmt = stmt.join(Identity, Identity.party_id == Party.party_id).where(
            Identity.tenant_id == tenant.tenant_id,
            Identity.value == identifier,
        )

    parties = db.execute(stmt).scalars().unique().all()
    return [PartyOut.model_validate(p) for p in parties]
