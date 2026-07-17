import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Identity, Tenant
from app.events.models import Event
from app.events.service import (
    last_interaction_channel,
    party_events,
    recent_events,
    record_event,
    resolve_last_channel,
)

DEMO = "+447700900000"


def _demo_party(db: Session, tenant: Tenant) -> uuid.UUID:
    return db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == tenant.tenant_id, Identity.value == DEMO
        )
    ).scalar_one()


def test_a_new_event_kind_needs_no_migration(db: Session, northwind: Tenant) -> None:
    """kind + JSONB payload: an unforeseen event type is just data."""
    party_id = _demo_party(db, northwind)

    record_event(
        db,
        northwind,
        party_id,
        "billing.autopay_failed",  # a kind no code has ever seen
        channel="email",
        payload={"amount": 42.5, "currency": "GBP", "attempt": 3},
    )

    stored = db.execute(
        select(Event).where(Event.kind == "billing.autopay_failed")
    ).scalar_one()
    assert stored.payload["amount"] == 42.5
    assert stored.payload["attempt"] == 3
    assert stored.channel == "email"


def test_record_event_is_tenant_and_party_scoped(db: Session, northwind: Tenant) -> None:
    party_id = _demo_party(db, northwind)
    event = record_event(db, northwind, party_id, "interaction", channel="voice")

    assert event.tenant_id == northwind.tenant_id
    assert event.party_id == party_id
    assert event.occurred_at is not None


def test_last_interaction_channel_is_none_before_any_event(
    db: Session, northwind: Tenant
) -> None:
    party_id = _demo_party(db, northwind)

    assert last_interaction_channel(db, northwind, party_id) is None


def test_resolve_last_channel_falls_back_then_prefers_events(
    db: Session, northwind: Tenant
) -> None:
    party_id = _demo_party(db, northwind)

    # No events yet → the fallback wins.
    assert resolve_last_channel(db, northwind, party_id, "sms") == "sms"

    record_event(db, northwind, party_id, "interaction", channel="webmessaging")

    # Now the real interaction wins over the fallback.
    assert resolve_last_channel(db, northwind, party_id, "sms") == "webmessaging"


def test_only_interaction_events_drive_last_channel(db: Session, northwind: Tenant) -> None:
    """A CSAT or telemetry event must not be mistaken for an interaction channel."""
    party_id = _demo_party(db, northwind)

    record_event(db, northwind, party_id, "csat", channel="csat", payload={"score": 5})
    record_event(db, northwind, party_id, "network.degraded", channel="telemetry")

    assert last_interaction_channel(db, northwind, party_id) is None
    assert resolve_last_channel(db, northwind, party_id, "sms") == "sms"


def test_party_events_filters_by_kind(db: Session, northwind: Tenant) -> None:
    party_id = _demo_party(db, northwind)
    record_event(db, northwind, party_id, "interaction", channel="voice")
    record_event(db, northwind, party_id, "csat", payload={"score": 5})

    assert len(party_events(db, northwind, party_id)) == 2
    assert len(party_events(db, northwind, party_id, kinds=("csat",))) == 1


def test_recent_events_are_tenant_scoped(
    db: Session, northwind: Tenant, seeded_acme: None
) -> None:
    acme = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()
    northwind_party = _demo_party(db, northwind)
    acme_party = db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == acme.tenant_id, Identity.value == "+447700901000"
        )
    ).scalar_one()

    record_event(db, northwind, northwind_party, "interaction", channel="voice")
    record_event(db, acme, acme_party, "interaction", channel="sms")

    assert len(recent_events(db, northwind)) == 1
    assert len(recent_events(db, acme)) == 1
    assert recent_events(db, northwind)[0].channel == "voice"
    assert recent_events(db, acme)[0].channel == "sms"
