"""/gx/order-action — place an order and confirm it, idempotently.

The idempotency tests are the important ones: an agent that retries, or a customer who
asks twice, must not end up with two orders.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.events.models import KIND_ORDER_CONFIRMATION_SENT, Event
from app.modules.orders.models import CustomerOrder

DEMO = "+447700900000"
OTHER = "+447700900001"
UNKNOWN = "+447700900999"
ACME_PHONE = "+447700901000"
OFFER = "NW-MESH-PRO"

FLAT_TYPES = (str, int, float, bool)


def order_action(
    client: TestClient, headers: dict[str, str], action: str, target: str, identifier: str = DEMO
) -> Any:
    return client.post(
        "/gx/order-action",
        json={"identifier": identifier, "action": action, "target": target},
        headers=headers,
    )


def place(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> dict:
    return order_action(client, auth, "place", OFFER, identifier).json()


def _count_orders(db: Session) -> int:
    return db.execute(select(func.count()).select_from(CustomerOrder)).scalar_one()


def test_requires_api_key(client: TestClient) -> None:
    assert client.post("/gx/order-action", json={}).status_code == 401


# ── place ────────────────────────────────────────────────────────────────────────────


def test_place_creates_an_order(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    body = place(client, auth)

    assert body["ok"] is True
    assert body["action"] == "place"
    assert body["order_id"]
    assert body["status"] == "placed"
    assert body["eta_text"]
    assert _count_orders(db) == 1


def test_place_persists_what_was_bought(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    """Name and price are snapshotted: the catalogue may change, the purchase may not."""
    place(client, auth)

    order = db.execute(select(CustomerOrder)).scalar_one()
    assert order.offer_id == OFFER
    assert order.offer_name == "Northwind Mesh Pro"
    assert float(order.price_gbp) == 6.0


def test_the_response_is_flat(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    for key, value in place(client, auth).items():
        assert isinstance(value, FLAT_TYPES), f"{key} is nested: {value!r}"
        assert value is not None


def test_place_is_idempotent(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    """Asking for the same offer twice returns the original order, not a second one."""
    first = place(client, auth)
    second = place(client, auth)

    assert second["ok"] is True
    assert second["order_id"] == first["order_id"]
    assert "already ordered" in second["result_summary"]
    assert _count_orders(db) == 1


# ── send-confirmation ────────────────────────────────────────────────────────────────


def test_send_confirmation_masks_the_address(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    order_id = place(client, auth)["order_id"]

    body = order_action(client, auth, "send-confirmation", order_id).json()

    assert body["ok"] is True
    assert body["message_ref"]
    assert body["status"] == "confirmed"
    # Masked so the agent can confirm where it went without reciting the address.
    assert body["sent_to_masked"].endswith("@example.net")
    assert "•" in body["sent_to_masked"]
    assert "anne" not in body["sent_to_masked"].lower()


def test_send_confirmation_records_an_event(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    order_id = place(client, auth)["order_id"]
    order_action(client, auth, "send-confirmation", order_id)

    events = (
        db.execute(select(Event).where(Event.kind == KIND_ORDER_CONFIRMATION_SENT))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["order_id"] == order_id


def test_send_confirmation_is_idempotent(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    """A resend reports the original reference and records nothing new."""
    order_id = place(client, auth)["order_id"]

    first = order_action(client, auth, "send-confirmation", order_id).json()
    second = order_action(client, auth, "send-confirmation", order_id).json()

    assert second["ok"] is True
    assert second["message_ref"] == first["message_ref"]
    assert "already been sent" in second["result_summary"]

    events = db.execute(
        select(func.count()).select_from(Event).where(Event.kind == KIND_ORDER_CONFIRMATION_SENT)
    ).scalar_one()
    assert events == 1


def test_both_verbs_share_one_key_set(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """One endpoint is one contract, so a flow binds the same fields for either verb."""
    placed = place(client, auth)
    confirmed = order_action(client, auth, "send-confirmation", placed["order_id"]).json()

    assert placed.keys() == confirmed.keys()


# ── bad input → flat 4xx, never a 500 ────────────────────────────────────────────────


def _assert_flat_error(response: Any, expected_status: int) -> None:
    assert response.status_code == expected_status
    body = response.json()
    assert body["ok"] is False
    assert body["result_summary"]
    # Flat, not nested under "detail".
    assert "detail" not in body
    for value in body.values():
        assert isinstance(value, FLAT_TYPES)


def test_unknown_action_is_a_flat_400(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(order_action(client, auth, "refund-everything", OFFER), 400)


def test_unknown_offer_is_a_flat_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(order_action(client, auth, "place", "NO-SUCH-OFFER"), 404)


def test_empty_target_is_a_flat_400(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(order_action(client, auth, "place", ""), 400)


def test_unknown_order_is_a_flat_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(
        order_action(client, auth, "send-confirmation", "00000000-0000-0000-0000-000000000000"),
        404,
    )


def test_a_target_that_is_not_a_uuid_is_a_flat_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(order_action(client, auth, "send-confirmation", "not-a-uuid"), 404)


def test_unknown_subscriber_is_a_flat_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    _assert_flat_error(order_action(client, auth, "place", OFFER, identifier=UNKNOWN), 404)


def test_a_failed_action_persists_nothing(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    order_action(client, auth, "place", "NO-SUCH-OFFER")

    assert _count_orders(db) == 0


# ── isolation and reset ──────────────────────────────────────────────────────────────


def test_orders_are_per_subscriber(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Session
) -> None:
    """The idempotency guard is scoped to one subscriber, not the whole tenant."""
    first = place(client, auth, identifier=DEMO)
    second = place(client, auth, identifier=OTHER)

    assert first["order_id"] != second["order_id"]
    assert _count_orders(db) == 2


def test_cross_tenant_order_does_not_leak(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    """A northwind subscriber must not resolve while scoped to acme."""
    r = order_action(client, {**auth, "X-Tenant": "acme"}, "place", OFFER, identifier=DEMO)

    assert r.status_code == 404


def test_confirmation_cannot_reach_another_subscribers_order(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    order_id = place(client, auth, identifier=DEMO)["order_id"]

    r = order_action(client, auth, "send-confirmation", order_id, identifier=OTHER)

    assert r.status_code == 404


def test_reset_clears_orders_and_order_events(
    client: TestClient,
    auth: dict[str, str],
    seeded_northwind: None,
    northwind: Tenant,
    db: Session,
) -> None:
    """A second demo take must start clean, or `place` would idempotently return
    take one's order instead of creating a fresh one."""
    from app.scenarios.engine import reset

    order_id = place(client, auth)["order_id"]
    order_action(client, auth, "send-confirmation", order_id)
    assert _count_orders(db) == 1

    reset(db, northwind)

    assert _count_orders(db) == 0
    assert (
        db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.kind == KIND_ORDER_CONFIRMATION_SENT)
        ).scalar_one()
        == 0
    )

    # Take two places a genuinely new order.
    second = place(client, auth)
    assert second["order_id"] != order_id
    assert "already ordered" not in second["result_summary"]


def test_reset_does_not_touch_another_tenants_orders(
    client: TestClient,
    auth: dict[str, str],
    seeded_northwind: None,
    seeded_acme: None,
    northwind: Tenant,
    db: Session,
) -> None:
    from sqlalchemy import select as sa_select

    from app.core.models import Identity
    from app.modules.offers.service import Offer
    from app.modules.orders.service import place_order
    from app.scenarios.engine import reset

    acme = db.execute(sa_select(Tenant).where(Tenant.slug == "acme")).scalar_one()
    acme_party = db.execute(
        sa_select(Identity.party_id).where(
            Identity.tenant_id == acme.tenant_id, Identity.value == ACME_PHONE
        )
    ).scalar_one()
    place_order(
        db,
        acme,
        acme_party,
        Offer(offer_id="A", name="A", price_gbp=1.0, reason="r", eta_text="e"),
    )
    db.commit()

    place(client, auth)
    assert _count_orders(db) == 2

    reset(db, northwind)

    remaining = db.execute(select(CustomerOrder)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].tenant_id == acme.tenant_id
