"""Admin: scenario controls (JSON) and the thin htmx UI.

Everything here depends on require_admin. The gx X-API-Key opens none of it.
"""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.admin.auth import AdminUser
from app.admin.schemas import (
    ActivityOut,
    ApplyIn,
    EventOut,
    ScenarioOut,
    ScenarioResultOut,
    SubscriberStateOut,
)
from app.admin.service import activity_feed, subscriber_states
from app.core.models import Tenant
from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.scenarios.engine import (
    ScenarioError,
    ScenarioNotFoundError,
    apply,
    list_scenarios,
    recent_events,
    reset,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])

DbDep = Annotated[Session, Depends(get_db)]


# ── control surface (JSON) ───────────────────────────────────────────────────────────


@router.get("/scenarios", response_model=list[ScenarioOut])
def get_scenarios(admin: AdminUser, tenant: CurrentTenant) -> list[ScenarioOut]:
    """Scenarios available to this tenant. Adding one is a YAML file, not a deploy."""
    return [
        ScenarioOut(
            name=s.name,
            title=s.title,
            description=s.description,
            reset_first=s.reset_first,
            subscribers=s.identifiers,
            steps=len(s.steps),
        )
        for s in list_scenarios(tenant.slug)
    ]


@router.post("/scenario/apply", response_model=ScenarioResultOut)
def post_apply(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep, payload: ApplyIn
) -> ScenarioResultOut:
    try:
        result = apply(db, tenant, payload.scenario)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ScenarioResultOut(
        ok=True,
        action=result.action,
        scenario=result.scenario,
        rows_changed=result.rows_changed,
        summary=result.summary,
    )


@router.post("/scenario/reset", response_model=ScenarioResultOut)
def post_reset(admin: AdminUser, tenant: CurrentTenant, db: DbDep) -> ScenarioResultOut:
    """Restore the seeded baseline. The between-takes button."""
    result = reset(db, tenant)
    return ScenarioResultOut(
        ok=True,
        action=result.action,
        scenario=result.scenario,
        rows_changed=result.rows_changed,
        summary=result.summary,
    )


@router.get("/subscribers", response_model=list[SubscriberStateOut])
def get_subscribers(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep
) -> list[SubscriberStateOut]:
    return subscriber_states(db, tenant)


@router.get("/events", response_model=list[EventOut])
def get_events(admin: AdminUser, tenant: CurrentTenant, db: DbDep) -> list[EventOut]:
    return [
        EventOut(
            action=e.action,
            scenario=e.scenario,
            summary=e.summary,
            rows_changed=e.rows_changed,
            created_at=e.created_at,
        )
        for e in recent_events(db, tenant)
    ]


@router.get("/activity", response_model=list[ActivityOut])
def get_activity(admin: AdminUser, tenant: CurrentTenant, db: DbDep) -> list[ActivityOut]:
    """Interaction, CSAT and telemetry events (the event store), newest first."""
    return activity_feed(db, tenant)


# ── the thin UI ──────────────────────────────────────────────────────────────────────
# Excluded from the OpenAPI schema: /docs documents the control surface above, and
# HTML fragments would only be noise there.


def _page_context(request: Request, tenant: Tenant, db: Session) -> dict[str, Any]:
    return {
        "request": request,
        "tenant": tenant,
        "subscribers": subscriber_states(db, tenant),
        "scenarios": list_scenarios(tenant.slug),
        "events": recent_events(db, tenant),
        "activity": activity_feed(db, tenant),
    }


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui_index(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep, request: Request
) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", _page_context(request, tenant, db))


@router.get("/fragments/state", response_class=HTMLResponse, include_in_schema=False)
def ui_state(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep, request: Request
) -> HTMLResponse:
    """The live-updating half of the page: subscriber table + event log."""
    return templates.TemplateResponse(request, "_state.html", _page_context(request, tenant, db))


@router.post("/ui/apply/{scenario}", response_class=HTMLResponse, include_in_schema=False)
def ui_apply(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep, request: Request, scenario: str
) -> HTMLResponse:
    try:
        apply(db, tenant, scenario)
    except ScenarioError as exc:
        context = _page_context(request, tenant, db)
        context["error"] = str(exc)
        return templates.TemplateResponse(request, "_state.html", context, status_code=400)

    return templates.TemplateResponse(request, "_state.html", _page_context(request, tenant, db))


@router.post("/ui/reset", response_class=HTMLResponse, include_in_schema=False)
def ui_reset(
    admin: AdminUser, tenant: CurrentTenant, db: DbDep, request: Request
) -> HTMLResponse:
    reset(db, tenant)
    return templates.TemplateResponse(request, "_state.html", _page_context(request, tenant, db))
