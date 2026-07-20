"""The gx surface Genesys binds to."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.core.tenancy import CurrentTenant
from app.db import get_db
from app.events.models import KIND_CSAT, KIND_INTERACTION
from app.events.service import (
    record_event,
    resolve_last_channel,
    telemetry_events,
)
from app.gx.masking import mask_name
from app.gx.normalize import normalize_identifier
from app.gx.schemas import (
    CsatIn,
    CsatOut,
    CustomerContextOut,
    DeviceActionIn,
    DeviceActionOut,
    DeviceOut,
    InteractionEventIn,
    InteractionEventOut,
    NetDiagnosticsOut,
    NetStatusOut,
    OffersOut,
    OrderActionIn,
    OrderActionOut,
    TelemetryOut,
    VerifyCustomerIn,
    VerifyCustomerOut,
)
from app.modules.network.actions import ACTION_HANDLERS, unknown_action
from app.modules.network.config import network_config
from app.modules.network.devices import describe_devices
from app.modules.network.faults import NO_FAULT, build_verdict, detect_all
from app.modules.network.service import Topology, load_topology
from app.modules.offers.service import best_offer
from app.modules.orders.actions import ACTION_HANDLERS as ORDER_ACTION_HANDLERS
from app.modules.orders.actions import unknown_action as unknown_order_action
from app.modules.profile.service import ProfileRollup, check_factor, resolve_profile

CSAT_MIN, CSAT_MAX = 1, 5

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
        # Real interaction history when it exists, else the BE-1 spine derivation.
        last_channel=resolve_last_channel(db, tenant, party.party_id, rollup.last_channel),
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


# ── Events: interaction history, CSAT write-back, telemetry seam ──────────────────────


@router.post("/interaction-event", response_model=InteractionEventOut)
def interaction_event(
    tenant: CurrentTenant,
    db: DbDep,
    payload: InteractionEventIn,
) -> Any:
    """Record an interaction. After this, customer-context sources last_channel from it."""
    base = InteractionEventOut(ok=False)
    rollup = _resolve(db, tenant, payload.identifier)
    if rollup is None:
        return JSONResponse(
            status_code=404,
            content=base.model_copy(update={"last_channel": ""}).model_dump(),
        )

    if not payload.channel.strip():
        return JSONResponse(status_code=400, content=base.model_dump())

    record_event(
        db,
        tenant,
        rollup.party.party_id,
        KIND_INTERACTION,
        channel=payload.channel,
        payload={"kind": payload.kind},
    )
    return InteractionEventOut(
        ok=True,
        party_id=str(rollup.party.party_id),
        stored=True,
        last_channel=payload.channel,
    )


@router.post("/csat", response_model=CsatOut)
def csat(
    tenant: CurrentTenant,
    db: DbDep,
    payload: CsatIn,
) -> Any:
    """Store a CSAT result written back by Genesys.

    For M1 the gx X-API-Key is sufficient. Third-party webhook signature validation
    (Open Messaging) is a Demo 4 concern — noted, not built here.
    """
    base = CsatOut(ok=False)

    if not (CSAT_MIN <= payload.score <= CSAT_MAX):
        return JSONResponse(status_code=400, content=base.model_dump())

    rollup = _resolve(db, tenant, payload.identifier)
    if rollup is None:
        return JSONResponse(status_code=404, content=base.model_dump())

    record_event(
        db,
        tenant,
        rollup.party.party_id,
        KIND_CSAT,
        channel="csat",
        conversation_ref=payload.conversation_ref,
        payload={"score": payload.score, "comment": payload.comment},
    )
    return CsatOut(ok=True, party_id=str(rollup.party.party_id), stored=True)


@router.get("/telemetry", response_model=list[TelemetryOut])
def telemetry(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[str, Query(description="ANI, email, or account number.")],
) -> list[TelemetryOut]:
    """The telemetry feed for a subscriber: a top-level array of flat events, newest
    first. Empty for an unknown or healthy subscriber, so a proactive poll can treat
    'nothing to do' uniformly. Not consumed by Genesys in M1 — this is the GX-C seam.
    """
    rollup = _resolve(db, tenant, identifier)
    if rollup is None:
        return []

    events = telemetry_events(db, tenant, rollup.party.party_id)
    return [
        TelemetryOut(
            party_id=str(e.party_id),
            kind=e.kind,
            fault_type=str(e.payload.get("fault_type", "")),
            primary_target=str(e.payload.get("primary_target", "")),
            primary_target_kind=str(e.payload.get("primary_target_kind", "")),
            primary_target_label=str(e.payload.get("primary_target_label", "")),
            recommended_action=str(e.payload.get("recommended_action", "")),
            conversation_ref=e.conversation_ref,
            occurred_at=e.occurred_at.isoformat(),
        )
        for e in events
    ]


# ── Devices, offers and orders ───────────────────────────────────────────────────────


@router.get("/devices", response_model=list[DeviceOut])
def devices(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[str, Query(description="ANI, email, or account number.")],
) -> list[DeviceOut]:
    """Every device in the subscriber's home, weakest signal first.

    A top-level array of flat objects — the one array shape a data action contract can
    express. Unknown subscriber returns an empty array rather than an error, so the
    agent can treat "nobody there" and "no devices" the same way.
    """
    rollup = _resolve(db, tenant, identifier)
    if rollup is None:
        return []

    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        return []

    views = describe_devices(topology, network_config(tenant))
    return [
        DeviceOut(
            device_id=v.device_id,
            label=v.label,
            kind=v.kind,
            band=v.band,
            rssi=v.rssi,
            ap_label=v.ap_label,
            steer_eligible=v.steer_eligible,
            status_summary=v.status_summary,
        )
        for v in views
    ]


@router.get("/offers", response_model=OffersOut)
def offers(
    tenant: CurrentTenant,
    db: DbDep,
    identifier: Annotated[str, Query(description="ANI, email, or account number.")],
) -> OffersOut:
    """The single best upgrade this subscriber's network justifies, if any.

    Eligibility is derived from their actual topology, so the reason given to the
    customer is true of them specifically. Not eligible returns the same key set with
    `eligible: false`, so one contract covers both branches.
    """
    rollup = _resolve(db, tenant, identifier)
    if rollup is None:
        return OffersOut(found=False)

    topology = load_topology(db, tenant, rollup.party.party_id)
    if topology.is_empty:
        return OffersOut(found=False)

    offer = best_offer(tenant, topology)
    if offer is None:
        return OffersOut(found=True, eligible=False)

    return OffersOut(
        found=True,
        eligible=True,
        offer_id=offer.offer_id,
        name=offer.name,
        price_gbp=offer.price_gbp,
        reason=offer.reason,
    )


def _order_error(payload: OrderActionOut, status_code: int) -> JSONResponse:
    """A flat 4xx. HTTPException would nest the body under 'detail'."""
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@router.post("/order-action", response_model=OrderActionOut)
def order_action(
    tenant: CurrentTenant,
    db: DbDep,
    payload: OrderActionIn,
) -> Any:
    """Place an order, or send its confirmation.

    Both verbs are idempotent: placing the same offer twice returns the original order,
    and re-sending a confirmation reports the original reference. A retrying agent
    cannot double-order.
    """
    base = OrderActionOut(ok=False, action=payload.action)

    rollup = _resolve(db, tenant, payload.identifier)
    if rollup is None:
        return _order_error(
            base.model_copy(update={"result_summary": "No subscriber for that identifier"}),
            404,
        )

    handler = ORDER_ACTION_HANDLERS.get(payload.action)
    if handler is None:
        outcome = unknown_order_action(payload.action)
        return _order_error(
            base.model_copy(update={"result_summary": outcome.result_summary}),
            outcome.status_code,
        )

    params = _parse_params(payload.params)
    if params is None:
        return _order_error(
            base.model_copy(update={"result_summary": "params must be a JSON object string"}),
            400,
        )

    outcome = handler(db, tenant, rollup.party, payload.target, params)
    if not outcome.ok:
        db.rollback()
        return _order_error(
            base.model_copy(update={"result_summary": outcome.result_summary}),
            outcome.status_code,
        )

    db.commit()

    return OrderActionOut(
        ok=True,
        action=payload.action,
        order_id=outcome.order_id,
        status=outcome.status,
        eta_text=outcome.eta_text,
        sent_to_masked=outcome.sent_to_masked,
        message_ref=outcome.message_ref,
        result_summary=outcome.result_summary,
    )
