"""Internal /v1 profile surface. gx wraps and flattens this."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.modules.profile.schemas import ProfileOut
from app.modules.profile.service import resolve_profile

router = APIRouter(prefix="/v1", tags=["profile"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("/profile", response_model=ProfileOut)
def get_profile(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[
        str,
        Query(description="Exact identity value. /v1 does not normalize; gx does."),
    ],
) -> ProfileOut:
    rollup = resolve_profile(db, tenant, identifier)
    if rollup is None:
        raise HTTPException(status_code=404, detail="No party for that identifier")
    return ProfileOut.from_rollup(rollup)
