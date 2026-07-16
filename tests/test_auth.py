from fastapi.testclient import TestClient


def test_v1_without_api_key_is_401(client: TestClient) -> None:
    r = client.get("/v1/tenants")

    assert r.status_code == 401
    assert "X-API-Key" in r.json()["detail"]


def test_v1_with_wrong_api_key_is_401(client: TestClient) -> None:
    r = client.get("/v1/tenants", headers={"X-API-Key": "not-the-key"})

    assert r.status_code == 401


def test_v1_with_correct_api_key_is_allowed(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/v1/tenants", headers=auth)

    assert r.status_code == 200


def test_parties_route_also_enforces_the_key(client: TestClient) -> None:
    assert client.get("/v1/parties").status_code == 401
