"""/gx/offers — the single best upgrade the subscriber's own topology justifies."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.modules.network.service import load_topology
from app.modules.offers.service import (
    Offer,
    UnknownEligibilityRule,
    best_offer,
    catalogue,
    is_eligible,
)

DEMO = "+447700900000"  # eligible: a device sits at the edge of the booster's range
NOT_ELIGIBLE = "+447700900001"  # a standard home, no coverage gap
NO_NETWORK = "+447700900009"
UNKNOWN = "+447700900999"
ACME_PHONE = "+447700901000"

FLAT_TYPES = (str, int, float, bool)


def offers(client: TestClient, headers: dict[str, str], identifier: str) -> dict:
    return client.get("/gx/offers", params={"identifier": identifier}, headers=headers).json()


def test_requires_api_key(client: TestClient) -> None:
    assert client.get("/gx/offers", params={"identifier": DEMO}).status_code == 401


def test_eligible_subscriber_gets_the_offer(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = offers(client, auth, DEMO)

    assert body["found"] is True
    assert body["eligible"] is True
    assert body["offer_id"] == "NW-MESH-PRO"
    assert body["name"] == "Northwind Mesh Pro"
    assert body["price_gbp"] == 6.0
    # The reason must be specific to this customer, not generic marketing.
    assert "upstairs" in body["reason"]


def test_the_response_is_flat(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    for key, value in offers(client, auth, DEMO).items():
        assert isinstance(value, FLAT_TYPES), f"{key} is nested: {value!r}"
        assert value is not None


def test_not_eligible_shares_an_identical_key_set(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """One contract must cover both branches, so a flow binds the same fields either way."""
    eligible = offers(client, auth, DEMO)
    not_eligible = offers(client, auth, NOT_ELIGIBLE)

    assert eligible.keys() == not_eligible.keys()
    assert not_eligible["found"] is True
    assert not_eligible["eligible"] is False
    assert not_eligible["offer_id"] == ""
    assert not_eligible["name"] == ""
    assert not_eligible["price_gbp"] == 0.0


def test_unknown_subscriber_is_found_false_with_the_same_keys(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = offers(client, auth, UNKNOWN)

    assert body["found"] is False
    assert body["eligible"] is False
    assert body.keys() == offers(client, auth, DEMO).keys()


def test_subscriber_without_a_network_is_found_false(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert offers(client, auth, NO_NETWORK)["found"] is False


def test_eligibility_survives_the_self_heal(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """The coverage gap is a property of the home, not of the transient fault: the
    upsell must still stand after the immediate problem is fixed."""
    assert offers(client, auth, DEMO)["eligible"] is True

    verdict = client.get(
        "/gx/net-diagnostics", params={"identifier": DEMO}, headers=auth
    ).json()
    client.post(
        "/gx/device-action",
        json={"identifier": DEMO, "action": "band-steer", "target": verdict["primary_target"]},
        headers=auth,
    )

    assert offers(client, auth, DEMO)["eligible"] is True


def test_cross_tenant_lookup_does_not_leak(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    body = offers(client, {**auth, "X-Tenant": "acme"}, DEMO)

    assert body["found"] is False
    assert body["offer_id"] == ""


def test_a_tenant_with_no_catalogue_is_never_eligible(
    client: TestClient, auth: dict[str, str], seeded_acme: None
) -> None:
    body = offers(client, {**auth, "X-Tenant": "acme"}, ACME_PHONE)

    assert body["found"] is True
    assert body["eligible"] is False


# ── the rules are pack config, not code ──────────────────────────────────────────────


def test_the_catalogue_comes_from_the_pack(northwind: Tenant) -> None:
    offers_available = catalogue(northwind)

    assert [o.offer_id for o in offers_available] == ["NW-MESH-PRO"]
    assert offers_available[0].eta_text  # falls back to default_eta_text


def test_eligibility_is_evaluated_against_the_real_topology(
    db: Session, northwind: Tenant, seeded_northwind: None
) -> None:
    """No subscriber id anywhere: the rule reads the topology it is given."""
    from sqlalchemy import select

    from app.core.models import Identity

    def topology_for(identifier: str):
        party_id = db.execute(
            select(Identity.party_id).where(
                Identity.tenant_id == northwind.tenant_id, Identity.value == identifier
            )
        ).scalar_one()
        return load_topology(db, northwind, party_id)

    offer = catalogue(northwind)[0]

    assert is_eligible(offer, topology_for(DEMO)) is True
    assert is_eligible(offer, topology_for(NOT_ELIGIBLE)) is False


def test_an_offer_with_no_conditions_is_always_eligible(
    db: Session, northwind: Tenant, seeded_northwind: None
) -> None:
    from sqlalchemy import select

    from app.core.models import Identity

    party_id = db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == northwind.tenant_id, Identity.value == NOT_ELIGIBLE
        )
    ).scalar_one()
    topology = load_topology(db, northwind, party_id)

    unconditional = Offer(
        offer_id="X", name="X", price_gbp=1.0, reason="r", eta_text="e", eligibility={}
    )

    assert is_eligible(unconditional, topology) is True


def test_an_unknown_eligibility_rule_fails_loudly(
    db: Session, northwind: Tenant, seeded_northwind: None
) -> None:
    """A typo in a pack must not silently make everyone eligible."""
    from sqlalchemy import select

    from app.core.models import Identity

    party_id = db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == northwind.tenant_id, Identity.value == DEMO
        )
    ).scalar_one()
    topology = load_topology(db, northwind, party_id)

    typo = Offer(
        offer_id="X",
        name="X",
        price_gbp=1.0,
        reason="r",
        eta_text="e",
        eligibility={"device_on_extender_rssi_at_or_bellow": -58},
    )

    with pytest.raises(UnknownEligibilityRule, match="unknown eligibility rule"):
        is_eligible(typo, topology)


def test_best_offer_is_none_when_nothing_applies(
    db: Session, northwind: Tenant, seeded_northwind: None
) -> None:
    from sqlalchemy import select

    from app.core.models import Identity

    party_id = db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == northwind.tenant_id, Identity.value == NOT_ELIGIBLE
        )
    ).scalar_one()

    assert best_offer(northwind, load_topology(db, northwind, party_id)) is None
