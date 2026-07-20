from typing import Any

from fastapi.testclient import TestClient

from tests.test_gx_customer_context import assert_flat

DEGRADED = "+447700900000"  # the demo subscriber; healthy until wifi_degraded is applied
HEALTHY = "+447700900001"
NO_NETWORK = "+447700900009"  # seeded party with no topology assigned
UNKNOWN = "+447700900999"
ACME_PHONE = "+447700901000"


def diagnostics(client: TestClient, headers: dict[str, str], identifier: str) -> dict:
    return client.get(
        "/gx/net-diagnostics", params={"identifier": identifier}, headers=headers
    ).json()


def status(client: TestClient, auth: dict[str, str], identifier: str) -> dict:
    return client.get("/gx/net-status", params={"identifier": identifier}, headers=auth).json()


def act(
    client: TestClient,
    auth: dict[str, str],
    identifier: str,
    action: str,
    target: str,
    **extra: str,
) -> Any:
    return client.post(
        "/gx/device-action",
        json={"identifier": identifier, "action": action, "target": target, **extra},
        headers=auth,
    )


# ── diagnostics ──────────────────────────────────────────────────────────────────────


def test_requires_api_key(client: TestClient) -> None:
    assert client.get("/gx/net-diagnostics", params={"identifier": DEGRADED}).status_code == 401
    assert client.get("/gx/net-status", params={"identifier": DEGRADED}).status_code == 401
    assert client.post("/gx/device-action", json={}).status_code == 401


def test_demo_subscriber_returns_the_staged_fault(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = diagnostics(client, auth, DEGRADED)

    assert body["found"] is True
    assert body["fault_type"] == "device_band_stuck"
    assert body["primary_target_kind"] == "device"
    assert body["primary_target"]
    assert body["primary_target_label"]  # names the device so a flow need not look it up
    assert body["recommended_action"] == "band-steer"
    assert body["wan_ok"] is True
    assert body["worst_device_band"] == "2.4"
    assert body["worst_device_rssi"] == -78
    assert body["extender_status"] == "flapping"


def test_diagnostics_is_flat(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    assert_flat(diagnostics(client, auth, DEGRADED))


def test_healthy_subscriber_returns_no_fault(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = diagnostics(client, auth, HEALTHY)

    assert body["found"] is True
    assert body["fault_type"] == "none"
    assert body["recommended_action"] == "none"
    assert body["primary_target"] == ""
    assert_flat(body)


def test_unknown_subscriber_is_found_false_not_an_error(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = diagnostics(client, auth, UNKNOWN)

    assert body["found"] is False
    assert_flat(body)


def test_subscriber_without_a_network_is_found_false(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = diagnostics(client, auth, NO_NETWORK)

    assert body["found"] is False


def test_found_and_not_found_share_a_key_set(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    assert diagnostics(client, auth, DEGRADED).keys() == diagnostics(client, auth, UNKNOWN).keys()


def test_diagnostics_normalizes_the_identifier(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    for spelling in (" 447700900000", "07700900000"):
        assert diagnostics(client, auth, spelling)["fault_type"] == "device_band_stuck"


def test_cross_tenant_diagnostics_does_not_leak(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None, seeded_acme: None
) -> None:
    body = diagnostics(client, {**auth, "X-Tenant": "acme"}, DEGRADED)

    assert body["found"] is False
    assert body["party_id"] == ""


# ── net-status ───────────────────────────────────────────────────────────────────────


def test_status_reports_the_staged_fault(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = status(client, auth, DEGRADED)

    assert body["found"] is True
    assert body["healthy"] is False
    assert body["fault_type"] == "device_band_stuck"
    assert body["wan_status"] == "online"
    assert body["gateway_model"] == "Northwind Hub 6"
    assert body["ap_total"] == 2
    assert body["ap_online"] == 1  # the extender is flapping
    assert body["device_total"] == 4
    assert_flat(body)


def test_status_for_a_healthy_subscriber(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    body = status(client, auth, HEALTHY)

    assert body["healthy"] is True
    assert body["fault_type"] == "none"


# ── device-action ────────────────────────────────────────────────────────────────────


def test_band_steer_clears_the_fault_and_mutates_state(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    target = diagnostics(client, auth, DEGRADED)["primary_target"]

    r = act(client, auth, DEGRADED, "band-steer", target)
    body = r.json()

    assert r.status_code == 200
    assert body["ok"] is True
    assert body["fault_cleared"] is True
    assert_flat(body)

    # The change is durable, and the next fault surfaces.
    after = diagnostics(client, auth, DEGRADED)
    assert after["fault_type"] == "extender_flapping"
    assert after["worst_device_band"] != "2.4" or after["worst_device_rssi"] > -78


def test_the_full_self_heal_sequence(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """The demo path: diagnose → band-steer → diagnose → reboot-extender → healthy."""
    first = diagnostics(client, auth, DEGRADED)
    assert first["fault_type"] == "device_band_stuck"

    assert act(client, auth, DEGRADED, "band-steer", first["primary_target"]).json()[
        "fault_cleared"
    ]

    second = diagnostics(client, auth, DEGRADED)
    assert second["fault_type"] == "extender_flapping"
    assert second["recommended_action"] == "reboot-extender"

    assert act(client, auth, DEGRADED, "reboot-extender", second["primary_target"]).json()[
        "fault_cleared"
    ]

    final = status(client, auth, DEGRADED)
    assert final["healthy"] is True
    assert final["fault_type"] == "none"
    assert final["extender_status"] == "online"
    assert final["ap_online"] == 2


def test_reboot_extender_mutates_the_extender(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    network = client.get("/v1/network", params={"identifier": DEGRADED}, headers=auth).json()
    extender = next(ap for ap in network["access_points"] if ap["kind"] == "extender")
    assert extender["status"] == "flapping"

    body = act(client, auth, DEGRADED, "reboot-extender", extender["ap_id"]).json()
    assert body["ok"] is True

    after = client.get("/v1/network", params={"identifier": DEGRADED}, headers=auth).json()
    rebooted = next(ap for ap in after["access_points"] if ap["kind"] == "extender")
    assert rebooted["status"] == "online"
    assert rebooted["backhaul_quality"] == 92


def test_reboot_ap_reattaches_devices(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    network = client.get("/v1/network", params={"identifier": DEGRADED}, headers=auth).json()
    hub = next(ap for ap in network["access_points"] if ap["kind"] == "gateway")

    r = act(client, auth, DEGRADED, "reboot-ap", hub["ap_id"])

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "reattached" in body["result_summary"]


def test_band_steer_accepts_params_as_a_json_string(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    target = diagnostics(client, auth, DEGRADED)["primary_target"]

    r = act(client, auth, DEGRADED, "band-steer", target, params='{"band":"5"}')

    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── error paths: clean flat 4xx, never a 500 ─────────────────────────────────────────


def test_unknown_target_is_a_flat_404(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    r = act(client, auth, DEGRADED, "band-steer", "00000000-0000-0000-0000-000000000000")

    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["result_summary"]
    assert_flat(body)


def test_a_target_that_is_not_even_a_uuid_is_a_flat_404(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    r = act(client, auth, DEGRADED, "band-steer", "not-a-uuid")

    assert r.status_code == 404
    assert_flat(r.json())


def test_unknown_action_is_a_flat_400(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    target = diagnostics(client, auth, DEGRADED)["primary_target"]

    r = act(client, auth, DEGRADED, "reticulate-splines", target)

    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert "Unknown action" in body["result_summary"]
    assert_flat(body)


def test_wrong_verb_for_the_target_is_a_flat_400(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """reboot-extender aimed at the gateway, not an extender."""
    network = client.get("/v1/network", params={"identifier": DEGRADED}, headers=auth).json()
    hub = next(ap for ap in network["access_points"] if ap["kind"] == "gateway")

    r = act(client, auth, DEGRADED, "reboot-extender", hub["ap_id"])

    assert r.status_code == 400
    assert "not an extender" in r.json()["result_summary"]
    assert_flat(r.json())


def test_band_steer_on_a_non_steerable_device_is_a_flat_400(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    network = client.get("/v1/network", params={"identifier": DEGRADED}, headers=auth).json()
    tv = next(d for d in network["devices"] if not d["steer_eligible"])

    r = act(client, auth, DEGRADED, "band-steer", tv["device_id"])

    assert r.status_code == 400
    assert "not steer-eligible" in r.json()["result_summary"]


def test_unknown_subscriber_action_is_a_flat_404(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    r = act(client, auth, UNKNOWN, "band-steer", "00000000-0000-0000-0000-000000000000")

    assert r.status_code == 404
    assert_flat(r.json())


def test_malformed_params_is_a_flat_400(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    target = diagnostics(client, auth, DEGRADED)["primary_target"]

    r = act(client, auth, DEGRADED, "band-steer", target, params="not json")

    assert r.status_code == 400
    assert_flat(r.json())


# ── cross-tenant ─────────────────────────────────────────────────────────────────────


def test_cross_tenant_action_cannot_mutate_another_tenants_device(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None, seeded_acme: None
) -> None:
    """An acme-scoped call must not touch a northwind device, even given its real id."""
    northwind_target = diagnostics(client, auth, DEGRADED)["primary_target"]

    r = client.post(
        "/gx/device-action",
        json={"identifier": ACME_PHONE, "action": "band-steer", "target": northwind_target},
        headers={**auth, "X-Tenant": "acme"},
    )

    assert r.status_code == 404
    # northwind's device is untouched.
    assert diagnostics(client, auth, DEGRADED)["fault_type"] == "device_band_stuck"
    assert diagnostics(client, auth, DEGRADED)["worst_device_rssi"] == -78


def test_each_tenant_diagnoses_its_own_network(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None, seeded_acme: None
) -> None:
    acme = diagnostics(client, {**auth, "X-Tenant": "acme"}, ACME_PHONE)

    assert acme["found"] is True
    assert acme["primary_target_label"] == "Acme Phone"
