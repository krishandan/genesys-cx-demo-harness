from fastapi.testclient import TestClient

SEEDED_PHONE = "+447700900000"
ACME_PHONE = "+447700901000"


def test_tenants_resolves_the_default_tenant(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/v1/tenants", headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert [t["slug"] for t in body] == ["northwind"]


def test_tenants_honours_the_x_tenant_header(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    r = client.get("/v1/tenants", headers={**auth, "X-Tenant": "acme"})

    assert r.status_code == 200
    assert [t["slug"] for t in r.json()] == ["acme"]


def test_unknown_tenant_is_404(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get("/v1/tenants", headers={**auth, "X-Tenant": "nope"})

    assert r.status_code == 404


def test_parties_resolves_a_seeded_subscriber_by_phone(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    # params= rather than an f-string: a literal '+' in a query string decodes to a
    # space, so an E.164 number must arrive percent-encoded.
    r = client.get("/v1/parties", params={"identifier": SEEDED_PHONE}, headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    party = body[0]
    assert party["display_name"]
    assert SEEDED_PHONE in [i["value"] for i in party["identities"]]


def test_parties_resolves_by_email_and_account_no(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    by_phone = client.get(
        "/v1/parties", params={"identifier": SEEDED_PHONE}, headers=auth
    ).json()[0]

    email = next(i["value"] for i in by_phone["identities"] if i["id_type"] == "email")
    account = next(i["value"] for i in by_phone["identities"] if i["id_type"] == "account_no")

    for identifier in (email, account):
        r = client.get("/v1/parties", params={"identifier": identifier}, headers=auth)
        assert r.status_code == 200
        assert r.json()[0]["party_id"] == by_phone["party_id"]


def test_parties_lists_only_the_scoped_tenants_parties(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    northwind = client.get("/v1/parties", headers=auth).json()
    acme = client.get("/v1/parties", headers={**auth, "X-Tenant": "acme"}).json()

    assert len(northwind) == 10
    assert len(acme) == 3

    northwind_ids = {p["party_id"] for p in northwind}
    acme_ids = {p["party_id"] for p in acme}
    assert northwind_ids.isdisjoint(acme_ids)


def test_foreign_tenant_lookup_does_not_leak_a_party(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    """A Northwind phone must not resolve while scoped to Acme."""
    r = client.get(
        "/v1/parties", params={"identifier": SEEDED_PHONE}, headers={**auth, "X-Tenant": "acme"}
    )

    assert r.status_code == 200
    assert r.json() == []


def test_acme_phone_does_not_resolve_under_northwind(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    r = client.get("/v1/parties", params={"identifier": ACME_PHONE}, headers=auth)

    assert r.status_code == 200
    assert r.json() == []


def test_unknown_identifier_returns_empty(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/v1/parties", params={"identifier": "+441234567890"}, headers=auth)

    assert r.status_code == 200
    assert r.json() == []
