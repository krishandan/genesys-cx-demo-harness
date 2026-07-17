"""Admin and gx are separate trust domains. Both directions are pinned here.

Genesys holds the gx X-API-Key. If that key could stage or reset a demo, a flow bug
could wipe the state mid-presentation; if the admin credential could read /gx, the
operator login would be a customer-data credential. Neither is allowed.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY

ADMIN = ("admin", "test-admin-password")
BAD_ADMIN = ("admin", "wrong")

ADMIN_ENDPOINTS = [
    ("GET", "/admin/"),
    ("GET", "/admin/subscribers"),
    ("GET", "/admin/scenarios"),
    ("GET", "/admin/events"),
    ("GET", "/admin/activity"),
    ("POST", "/admin/scenario/reset"),
]

GX_ENDPOINTS = [
    ("GET", "/gx/customer-context?identifier=%2B447700900000"),
    ("GET", "/gx/net-status?identifier=%2B447700900000"),
    ("GET", "/gx/net-diagnostics?identifier=%2B447700900000"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_admin_needs_credentials(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_the_gx_api_key_does_not_open_admin(
    client: TestClient, method: str, path: str, seeded_northwind: None
) -> None:
    r = client.request(method, path, headers={"X-API-Key": TEST_API_KEY})

    assert r.status_code == 401, f"the Genesys key opened {path}"


@pytest.mark.parametrize(("method", "path"), GX_ENDPOINTS)
def test_admin_credentials_do_not_open_gx(
    client: TestClient, method: str, path: str, seeded_northwind: None
) -> None:
    r = client.request(method, path, auth=ADMIN)

    assert r.status_code == 401, f"the admin credential opened {path}"


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_wrong_admin_password_is_rejected(
    client: TestClient, method: str, path: str, seeded_northwind: None
) -> None:
    assert client.request(method, path, auth=BAD_ADMIN).status_code == 401


def test_wrong_admin_user_is_rejected(client: TestClient, seeded_northwind: None) -> None:
    assert client.get("/admin/subscribers", auth=("root", "test-admin-password")).status_code == 401


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
def test_correct_admin_credentials_are_accepted(
    client: TestClient, method: str, path: str, seeded_northwind: None
) -> None:
    assert client.request(method, path, auth=ADMIN).status_code == 200


def test_admin_challenges_with_basic_so_a_browser_prompts(client: TestClient) -> None:
    r = client.get("/admin/")

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")


def test_both_credentials_together_still_work_for_each_surface(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """Sending both is harmless: each surface consults only its own credential."""
    assert client.get("/admin/subscribers", headers=auth, auth=ADMIN).status_code == 200
    assert (
        client.get(
            "/gx/customer-context", params={"identifier": "+447700900000"}, headers=auth, auth=ADMIN
        ).status_code
        == 200
    )
