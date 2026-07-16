from fastapi.testclient import TestClient


def test_health_is_public_and_reports_default_tenant(client: TestClient) -> None:
    r = client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["tenant_default"] == "northwind"
    assert "version" in body


def test_openapi_surface_is_public(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_openapi_documents_the_v1_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/health" in paths
    assert "/v1/tenants" in paths
    assert "/v1/parties" in paths
