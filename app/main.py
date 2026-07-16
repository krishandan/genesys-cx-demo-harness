"""Backlot FastAPI application."""

from fastapi import FastAPI

from app.auth.middleware import ApiKeyMiddleware
from app.config import get_settings
from app.core.routes import router as core_router
from app.core.schemas import HealthOut
from app.gx.routes import router as gx_router
from app.logging import configure_logging
from app.modules.profile.routes import router as profile_router

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Backlot",
    description="Reusable backend harness for Genesys Cloud demos.",
    version=settings.app_version,
)

app.add_middleware(ApiKeyMiddleware)

app.include_router(core_router)
app.include_router(profile_router)
app.include_router(gx_router)


@app.get("/health", response_model=HealthOut, tags=["ops"])
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        tenant_default=settings.default_tenant,
        version=settings.app_version,
    )
