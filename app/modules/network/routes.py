"""Internal /v1/network surface: the rich nested truth that gx flattens."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.modules.network.config import network_config
from app.modules.network.faults import build_verdict
from app.modules.network.schemas import NetworkOut
from app.modules.network.service import load_topology
from app.modules.profile.service import resolve_profile

router = APIRouter(prefix="/v1", tags=["network"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("/network", response_model=NetworkOut)
def get_network(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[
        str,
        Query(description="Exact identity value. /v1 does not normalize; gx does."),
    ],
) -> NetworkOut:
    rollup = resolve_profile(db, tenant, identifier)
    if rollup is None:
        raise HTTPException(status_code=404, detail="No party for that identifier")

    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        raise HTTPException(status_code=404, detail="That subscriber has no home network")

    cfg = network_config(tenant)
    return NetworkOut.build(topology, tenant.slug, build_verdict(topology, cfg))
