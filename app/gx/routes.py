"""The gx surface Genesys binds to."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.gx.masking import mask_name
from app.gx.normalize import normalize_identifier
from app.gx.schemas import (
    CustomerContextOut,
    DeviceActionIn,
    DeviceActionOut,
    NetDiagnosticsOut,
    NetStatusOut,
    VerifyCustomerIn,
    VerifyCustomerOut,
)
from app.modules.network.actions import ACTION_HANDLERS, unknown_action
from app.modules.network.config import network_config
from app.modules.network.faults import NO_FAULT, build_verdict, detect_all
from app.modules.network.service import Topology, load_topology
from app.modules.profile.service import ProfileRollup, check_factor, resolve_profile

router = APIRouter(prefix="/gx", tags=["gx"])

DbDep = Annotated[Session, Depends(get_db)]


def _country_of(tenant: Tenant) -> str | None:
    country = tenant.config_json.get("country")
    return str(country) if country else None


def _resolve(db: Session, tenant: Tenant, identifier: str) -> ProfileRollup | None:
    """Normalize at the gx boundary, then resolve. Every gx read starts here."""
    normalized = normalize_identifier(identifier, _country_of(tenant))
    if not normalized.recognized:
        return None
    return resolve_profile(db, tenant, normalized.value)


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


# ── Network & Devices ────────────────────────────────────────────────────────────────


@router.get("/net-diagnostics", response_model=NetDiagnosticsOut)
def net_diagnostics(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[str, Query(description="ANI, email, or account number.")],
) -> NetDiagnosticsOut:
    """Diagnose the subscriber's home network and return a flat verdict.

    The module walks the topology so the flow does not have to: the answer AVA needs is
    a fault type, a thing to act on, and the verb to call.
    """
    rollup = _resolve(db, tenant, identifier)
    if rollup is None:
        return NetDiagnosticsOut(found=False)

    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        return NetDiagnosticsOut(found=False, party_id=str(rollup.party.party_id))

    verdict = build_verdict(topology, network_config(tenant))
    return NetDiagnosticsOut(
        found=True,
        party_id=str(rollup.party.party_id),
        fault_type=verdict.fault_type,
        primary_target=verdict.primary_target,
        primary_target_kind=verdict.primary_target_kind,
        primary_target_label=verdict.primary_target_label,
        recommended_action=verdict.recommended_action,
        wan_ok=verdict.wan_ok,
        worst_device_band=verdict.worst_device_band,
        worst_device_rssi=verdict.worst_device_rssi,
        extender_status=verdict.extender_status,
    )


def _status_of(topology: Topology, tenant: Tenant, party_id: str) -> NetStatusOut:
    cfg = network_config(tenant)
    verdict = build_verdict(topology, cfg)
    target_band = cfg["steer_target_band"]
    worst = min(topology.devices, key=lambda d: d.rssi) if topology.devices else None

    return NetStatusOut(
        found=True,
        party_id=party_id,
        healthy=verdict.fault_type == NO_FAULT,
        fault_type=verdict.fault_type,
        wan_ok=verdict.wan_ok,
        wan_status=topology.gateway.wan_status if topology.gateway else "",
        gateway_model=topology.gateway.model if topology.gateway else "",
        gateway_uptime_s=topology.gateway.uptime_s if topology.gateway else 0,
        ap_total=len(topology.access_points),
        ap_online=sum(1 for ap in topology.access_points if ap.status == "online"),
        extender_status=verdict.extender_status,
        device_total=len(topology.devices),
        devices_on_target_band=sum(1 for d in topology.devices if d.band == target_band),
        worst_device_label=worst.label if worst else "",
        worst_device_band=worst.band if worst else "",
        worst_device_rssi=worst.rssi if worst else 0,
    )


@router.get("/net-status", response_model=NetStatusOut)
def net_status(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[str, Query(description="ANI, email, or account number.")],
) -> NetStatusOut:
    """Flat current state, for confirming recovery after an action."""
    rollup = _resolve(db, tenant, identifier)
    if rollup is None:
        return NetStatusOut(found=False)

    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        return NetStatusOut(found=False, party_id=str(rollup.party.party_id))

    return _status_of(topology, tenant, str(rollup.party.party_id))


def _action_error(payload: DeviceActionOut, status_code: int) -> JSONResponse:
    """A flat 4xx. HTTPException would nest the body under 'detail'."""
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _parse_params(raw: str) -> dict[str, Any] | None:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@router.post("/device-action", response_model=DeviceActionOut)
def device_action(
    tenant: CurrentTenant,
    db: DbDep,
    payload: DeviceActionIn,
) -> Any:
    """Run a verb against the subscriber's network and report whether it fixed the fault.

    New verbs register a handler in app/modules/network/actions.py; they need neither a
    new route here nor a new Genesys data action.
    """
    base = DeviceActionOut(ok=False, action=payload.action, target=payload.target)

    rollup = _resolve(db, tenant, payload.identifier)
    if rollup is None:
        return _action_error(
            base.model_copy(update={"result_summary": "No subscriber for that identifier"}),
            404,
        )

    handler = ACTION_HANDLERS.get(payload.action)
    if handler is None:
        outcome = unknown_action(payload.action)
        return _action_error(
            base.model_copy(update={"result_summary": outcome.result_summary}),
            outcome.status_code,
        )

    params = _parse_params(payload.params)
    if params is None:
        return _action_error(
            base.model_copy(update={"result_summary": "params must be a JSON object string"}),
            400,
        )

    cfg = network_config(tenant)
    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        return _action_error(
            base.model_copy(update={"result_summary": "That subscriber has no home network"}),
            404,
        )

    fault_before = build_verdict(topology, cfg).fault_type

    outcome = handler(db, topology, payload.target, params, cfg)
    if not outcome.ok:
        db.rollback()
        return _action_error(
            base.model_copy(update={"result_summary": outcome.result_summary}),
            outcome.status_code,
        )

    db.commit()

    # Re-read: fault_cleared must reflect committed state, not what we hoped happened.
    after = load_topology(db, tenant, rollup.party.party_id)
    still_firing = detect_all(after, cfg)
    fault_cleared = fault_before != NO_FAULT and fault_before not in still_firing

    return DeviceActionOut(
        ok=True,
        action=payload.action,
        target=payload.target,
        result_summary=outcome.result_summary,
        fault_cleared=fault_cleared,
    )
