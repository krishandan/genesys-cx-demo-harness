"""order-action verbs.

Handlers register by name, exactly like the network module's device-action, so a new
verb is a function here rather than a new gx route or a new Genesys data action.

Both verbs are idempotent per order: `place` returns an existing live order instead of
creating a second one, and `send-confirmation` keeps the first message reference. An
agent that retries — or a customer who asks twice — must not end up with two orders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import Party, Tenant
from app.events.models import KIND_ORDER_CONFIRMATION_SENT
from app.events.service import record_event
from app.gx.masking import mask_email
from app.modules.offers.service import find_offer
from app.modules.orders.service import (
    get_order,
    mark_confirmed,
    message_ref_for,
    place_order,
)


@dataclass(frozen=True)
class OrderOutcome:
    """One verb's result. Carries every field the flat gx response can report; the verb
    that does not produce a field simply leaves it empty."""

    ok: bool
    result_summary: str
    status_code: int = 200
    order_id: str = ""
    status: str = ""
    eta_text: str = ""
    sent_to_masked: str = ""
    message_ref: str = ""


Handler = Callable[[Session, Tenant, Party, str, dict[str, Any]], OrderOutcome]

ACTION_HANDLERS: dict[str, Handler] = {}


def action(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        ACTION_HANDLERS[name] = fn
        return fn

    return register


def _party_email(party: Party) -> str:
    """The subscriber's email, preferring a primary identity then any contact point."""
    emails = [i for i in party.identities if i.id_type == "email"]
    primary = next((i for i in emails if i.is_primary), None)
    if primary is not None:
        return primary.value
    if emails:
        return emails[0].value

    point = next((c for c in party.contact_points if c.channel == "email"), None)
    return point.value if point is not None else ""


@action("place")
def place(
    db: Session,
    tenant: Tenant,
    party: Party,
    target: str,
    params: dict[str, Any],
) -> OrderOutcome:
    """Place an order for an offer. `target` is the offer_id from get-offers."""
    if not target:
        return OrderOutcome(
            ok=False,
            result_summary="No offer_id supplied. Pass the offer_id from get-offers as target.",
            status_code=400,
        )

    offer = find_offer(tenant, target)
    if offer is None:
        return OrderOutcome(
            ok=False,
            result_summary=f"No offer '{target}' in the catalogue",
            status_code=404,
        )

    order, created = place_order(db, tenant, party.party_id, offer)

    summary = (
        f"Ordered {order.offer_name} at £{order.price_gbp:.2f} per month; {order.eta_text}"
        if created
        else f"{order.offer_name} was already ordered; no duplicate was created"
    )

    return OrderOutcome(
        ok=True,
        result_summary=summary,
        order_id=str(order.order_id),
        status=order.status,
        eta_text=order.eta_text,
    )


@action("send-confirmation")
def send_confirmation(
    db: Session,
    tenant: Tenant,
    party: Party,
    target: str,
    params: dict[str, Any],
) -> OrderOutcome:
    """Send the order confirmation. `target` is the order_id returned by place."""
    if not target:
        return OrderOutcome(
            ok=False,
            result_summary="No order_id supplied. Pass the order_id from place as target.",
            status_code=400,
        )

    order = get_order(db, tenant, party.party_id, target)
    if order is None:
        return OrderOutcome(
            ok=False,
            result_summary=f"No order '{target}' for this subscriber",
            status_code=404,
        )

    email = _party_email(party)
    if not email:
        return OrderOutcome(
            ok=False,
            result_summary="That subscriber has no email address on file",
            status_code=400,
        )

    masked = mask_email(email, tenant.config_json.get("masked_email"))
    already_sent = bool(order.confirmation_message_ref)
    message_ref = mark_confirmed(db, order)

    if not already_sent:
        # The event is the audit trail; the order's message ref is what makes the verb
        # idempotent, so a resend records nothing new.
        record_event(
            db,
            tenant,
            party.party_id,
            KIND_ORDER_CONFIRMATION_SENT,
            channel="email",
            payload={
                "order_id": str(order.order_id),
                "offer_id": order.offer_id,
                "offer_name": order.offer_name,
                "message_ref": message_ref,
                "sent_to_masked": masked,
            },
            commit=False,
        )

    summary = (
        f"Confirmation sent to {masked}"
        if not already_sent
        else f"Confirmation had already been sent to {masked}"
    )

    return OrderOutcome(
        ok=True,
        result_summary=summary,
        order_id=str(order.order_id),
        status=order.status,
        eta_text=order.eta_text,
        sent_to_masked=masked,
        message_ref=message_ref,
    )


def unknown_action(name: str) -> OrderOutcome:
    known = ", ".join(sorted(ACTION_HANDLERS))
    return OrderOutcome(
        ok=False,
        result_summary=f"Unknown action '{name}'. Known actions: {known}",
        status_code=400,
    )


__all__ = [
    "ACTION_HANDLERS",
    "OrderOutcome",
    "action",
    "message_ref_for",
    "place",
    "send_confirmation",
    "unknown_action",
]
