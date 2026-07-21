from typing import Any

from fastapi.testclient import TestClient

from tests.test_gx_customer_context import assert_flat

DEMO = "+447700900000"
HEALTHY = "+447700900001"
UNKNOWN = "+447700900999"
NO_NETWORK = "+447700900009"


def ctx(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> dict:
    return client.get(
        "/gx/customer-context", params={"identifier": identifier}, headers=auth
    ).json()


def interaction(client: TestClient, auth: dict[str, str], **body: Any):
    return client.post("/gx/interaction-event", json=body, headers=auth)


def csat(client: TestClient, auth: dict[str, str], **body: Any):
    return client.post("/gx/csat", json=body, headers=auth)


def telemetry(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> list:
    return client.get("/gx/telemetry", params={"identifier": identifier}, headers=auth).json()


# ── auth ─────────────────────────────────────────────────────────────────────────────


def test_event_endpoints_require_the_api_key(client: TestClient) -> None:
    assert client.post("/gx/interaction-event", json={}).status_code == 401
    assert client.post("/gx/csat", json={}).status_code == 401
    assert client.get("/gx/telemetry", params={"identifier": DEMO}).status_code == 401


# ── interaction events + last_channel (closes the BE-1 carryover) ─────────────────────


def test_last_channel_is_spine_derived_before_any_event(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = ctx(client, auth)

    # Resolved by phone → the sms contact point, per the BE-1 derivation.
    assert body["last_channel"] == "sms"


def test_last_channel_comes_from_the_event_after_one(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = interaction(client, auth, identifier=DEMO, channel="webmessaging", kind="inbound")
    body = r.json()

    assert r.status_code == 200
    assert body["ok"] is True
    assert body["stored"] is True
    assert body["last_channel"] == "webmessaging"

    # And customer-context now reports it.
    assert ctx(client, auth)["last_channel"] == "webmessaging"


def test_last_channel_follows_the_most_recent_interaction(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    interaction(client, auth, identifier=DEMO, channel="voice", kind="inbound")
    interaction(client, auth, identifier=DEMO, channel="webmessaging", kind="inbound")

    assert ctx(client, auth)["last_channel"] == "webmessaging"


def test_empty_kind_defaults_to_inbound(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, db: Any
) -> None:
    """`kind` is now a required contract input (an optional-but-referenced Velocity
    variable renders as a literal when omitted), so Genesys sends "" when it has nothing.
    The handler must keep the inbound default rather than storing an empty kind."""
    from sqlalchemy import select

    from app.events.models import KIND_INTERACTION, Event

    r = interaction(client, auth, identifier=DEMO, channel="sms", kind="")
    assert r.status_code == 200
    assert r.json()["stored"] is True

    event = db.execute(
        select(Event).where(Event.kind == KIND_INTERACTION).order_by(Event.occurred_at.desc())
    ).scalars().first()
    assert event is not None
    assert event.payload["kind"] == "inbound"


def test_interaction_unknown_subscriber_is_a_flat_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = interaction(client, auth, identifier=UNKNOWN, channel="voice", kind="inbound")

    assert r.status_code == 404
    assert_flat(r.json())
    assert r.json()["ok"] is False


def test_interaction_without_a_channel_is_a_flat_400(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = interaction(client, auth, identifier=DEMO, channel="", kind="inbound")

    assert r.status_code == 400
    assert_flat(r.json())


def test_interaction_normalizes_the_identifier(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    # National number, resolved via the tenant country.
    r = interaction(client, auth, identifier="07700900000", channel="sms", kind="inbound")

    assert r.status_code == 200
    assert r.json()["party_id"]


# ── CSAT write-back ──────────────────────────────────────────────────────────────────


def test_csat_stores_and_is_flat(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = csat(
        client, auth, identifier=DEMO, score=5, comment="fixed my wifi", conversation_ref="abc"
    )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["stored"] is True
    assert body["party_id"]
    assert_flat(body)


def test_csat_is_readable_back_in_the_admin_activity(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    csat(client, auth, identifier=DEMO, score=4, comment="ok", conversation_ref="c1")

    activity = client.get("/admin/activity", auth=("admin", "test-admin-password")).json()
    csat_rows = [a for a in activity if a["kind"] == "csat"]
    assert csat_rows
    assert csat_rows[0]["conversation_ref"] == "c1"
    assert "4" in csat_rows[0]["summary"]


def test_csat_bad_score_is_a_flat_400(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    for score in (0, 6, -1, 99):
        r = csat(client, auth, identifier=DEMO, score=score)
        assert r.status_code == 400, score
        assert_flat(r.json())
        assert r.json()["ok"] is False


def test_csat_boundary_scores_are_accepted(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert csat(client, auth, identifier=DEMO, score=1).status_code == 200
    assert csat(client, auth, identifier=DEMO, score=5).status_code == 200


def test_csat_unknown_subscriber_is_404(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = csat(client, auth, identifier=UNKNOWN, score=5)

    assert r.status_code == 404
    assert_flat(r.json())


# ── telemetry seam ───────────────────────────────────────────────────────────────────


def test_telemetry_is_empty_at_baseline(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert telemetry(client, auth) == []


def test_staging_the_fault_emits_telemetry(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    feed = telemetry(client, auth)

    assert len(feed) == 1
    event = feed[0]
    assert event["kind"] == "network.degraded"
    assert event["fault_type"] == "device_band_stuck"
    assert event["primary_target_label"] == "Ella's iPad"
    assert event["recommended_action"] == "band-steer"


def test_telemetry_items_are_flat(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    for item in telemetry(client, auth):
        assert_flat(item)


def test_telemetry_is_a_top_level_array(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = client.get("/gx/telemetry", params={"identifier": DEMO}, headers=auth).json()

    assert isinstance(body, list)


def test_telemetry_empty_for_unknown_or_healthy(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert telemetry(client, auth, UNKNOWN) == []
    assert telemetry(client, auth, HEALTHY) == []
    assert telemetry(client, auth, NO_NETWORK) == []


def test_outage_scenario_emits_wan_telemetry(
    client: TestClient, auth: dict[str, str], db: Any, northwind: Any
) -> None:
    from app.scenarios.engine import apply

    apply(db, northwind, "outage_in_area")

    feed = telemetry(client, auth)
    assert any(e["fault_type"] == "wan_degraded" for e in feed)


# ── cross-tenant isolation ───────────────────────────────────────────────────────────


def test_events_do_not_leak_across_tenants(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    # Record on northwind.
    interaction(client, auth, identifier=DEMO, channel="webmessaging", kind="inbound")
    csat(client, auth, identifier=DEMO, score=5)

    # The acme tenant sees none of it.
    acme_headers = {**auth, "X-Tenant": "acme"}
    acme_activity = client.get(
        "/admin/activity", auth=("admin", "test-admin-password"), headers={"X-Tenant": "acme"}
    ).json()
    assert acme_activity == []

    # And an acme-scoped telemetry read for a northwind number resolves nothing.
    assert client.get(
        "/gx/telemetry", params={"identifier": DEMO}, headers=acme_headers
    ).json() == []
