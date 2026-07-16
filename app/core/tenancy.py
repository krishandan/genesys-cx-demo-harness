"""Tenant resolution. Every data query in Backlot is scoped by the resolved tenant."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.models import Tenant
from app.db import get_db

TENANT_HEADER = "X-Tenant"


def resolve_tenant(
    db: Annotated[Session, Depends(get_db)],
    x_tenant: Annotated[str | None, Header(alias=TENANT_HEADER)] = None,
) -> Tenant:
    """Resolve the tenant from X-Tenant, falling back to DEFAULT_TENANT config."""
    slug = x_tenant or get_settings().default_tenant

    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{slug}'")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(resolve_tenant)]
