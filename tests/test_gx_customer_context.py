from typing import Any

from fastapi.testclient import TestClient

SEEDED_PHONE = "+447700900000"
UNKNOWN_PHONE = "+447700900999"


def assert_flat(payload: dict[str, Any]) -> None:
    """Genesys data action output contracts cannot express nested arrays."""
    for key, value in payload.items():
        assert not isinstance(value, (list, dict)), f"'{key}' is nested: {value!r}"
        assert value is not None, f"'{key}' is null; gx fields must always be typed"


def test_requires_api_key(client: TestClient) -> None:
    r = client.get("/gx/customer-context", params={"identifier": SEEDED_PHONE})

    assert r.status_code == 401


def test_resolves_a_seeded_subscriber(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": SEEDED_PHONE}, headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["party_id"]
    assert body["display_name"]
    assert body["tenant_slug"] == "northwind"
    assert body["tier"] in {"bronze", "silver", "gold"}
    assert body["id_type_resolved"] == "phone"
    # verified is a separate call; context never asserts identity.
    assert body["verified"] is False


def test_response_is_flat(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": SEEDED_PHONE}, headers=auth)

    assert_flat(r.json())


def test_not_found_is_200_with_found_false(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": UNKNOWN_PHONE}, headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["party_id"] == ""
    # Still the full flat shape, so a flow binds the same contract either way.
    assert_flat(body)


def test_not_found_response_is_flat_and_branchable(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    found = client.get(
        "/gx/customer-context", params={"identifier": SEEDED_PHONE}, headers=auth
    ).json()
    missing = client.get(
        "/gx/customer-context", params={"identifier": UNKNOWN_PHONE}, headers=auth
    ).json()

    # Identical key sets: one data action contract covers both outcomes.
    assert found.keys() == missing.keys()


def test_unrecognized_identifier_is_not_a_500(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": "???"}, headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["id_type_resolved"] == "unrecognized"


def test_space_decoded_plus_still_resolves(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """The BE-0 trap, now absorbed at the gx boundary: an unencoded '+' arrives as a
    space and must still resolve."""
    r = client.get("/gx/customer-context", params={"identifier": " 447700900000"}, headers=auth)

    assert r.status_code == 200
    assert r.json()["found"] is True


def test_national_number_resolves_via_tenant_country(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": "07700900000"}, headers=auth)

    assert r.status_code == 200
    assert r.json()["found"] is True


def test_resolves_by_email_and_account_no(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    by_phone = client.get(
        "/v1/profile", params={"identifier": SEEDED_PHONE}, headers=auth
    ).json()
    email = next(i["value"] for i in by_phone["identities"] if i["id_type"] == "email")
    account = next(i["value"] for i in by_phone["identities"] if i["id_type"] == "account_no")

    for identifier, expected_type in ((email, "email"), (account, "account_no")):
        r = client.get("/gx/customer-context", params={"identifier": identifier}, headers=auth)
        body = r.json()
        assert body["found"] is True
        assert body["party_id"] == by_phone["party_id"]
        assert body["id_type_resolved"] == expected_type


def test_cross_tenant_lookup_does_not_leak(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    r = client.get(
        "/gx/customer-context",
        params={"identifier": SEEDED_PHONE},
        headers={**auth, "X-Tenant": "acme"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["display_name"] == ""
    assert body["party_id"] == ""


def test_last_channel_is_populated(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/customer-context", params={"identifier": SEEDED_PHONE}, headers=auth)

    # Resolved by phone, so the sms contact point is the matching channel.
    assert r.json()["last_channel"] == "sms"
