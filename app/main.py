"""Backlot FastAPI application."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.admin.routes import router as admin_router
from app.auth.middleware import ApiKeyMiddleware
from app.config import get_settings
from app.core.routes import router as core_router
from app.core.schemas import HealthOut
from app.gx.routes import router as gx_router
from app.logging import configure_logging
from app.modules.network.routes import router as network_router
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
app.include_router(network_router)
app.include_router(gx_router)
app.include_router(admin_router)

# htmx is vendored rather than pulled from a CDN: the admin UI has to work on a box
# whose only outbound path is the tunnel.
app.mount(
    "/admin/static",
    StaticFiles(directory=str(Path(__file__).parent / "admin" / "static")),
    name="admin-static",
)


@app.get("/health", response_model=HealthOut, tags=["ops"])
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        tenant_default=settings.default_tenant,
        version=settings.app_version,
    )
