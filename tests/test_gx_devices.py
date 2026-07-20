"""/gx/devices — the tool the agent uses to match a device the customer names."""

from fastapi.testclient import TestClient

DEMO = "+447700900000"
HEALTHY = "+447700900001"
NO_NETWORK = "+447700900009"
UNKNOWN = "+447700900999"
ACME_PHONE = "+447700901000"

FLAT_TYPES = (str, int, float, bool)


def devices(client: TestClient, headers: dict[str, str], identifier: str) -> list[dict]:
    return client.get("/gx/devices", params={"identifier": identifier}, headers=headers).json()


def test_requires_api_key(client: TestClient) -> None:
    assert client.get("/gx/devices", params={"identifier": DEMO}).status_code == 401


def test_returns_a_top_level_array_of_flat_objects(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """A top-level array is the one array shape a data action contract can express."""
    body = devices(client, auth, DEMO)

    assert isinstance(body, list)
    assert body
    for row in body:
        assert isinstance(row, dict)
        for key, value in row.items():
            assert isinstance(value, FLAT_TYPES), f"{key} is nested: {value!r}"
            assert value is not None


def test_the_named_family_devices_are_present(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """The customer says "my daughter's iPad"; the agent has to find it by that name."""
    labels = {d["label"] for d in devices(client, auth, DEMO)}

    assert "Ella's iPad" in labels
    assert "Work Laptop" in labels
    assert any(label.endswith("'s Phone") for label in labels)


def test_devices_carry_a_kind_for_matching_by_type(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """So "the tablet" resolves as well as "Ella's iPad"."""
    by_label = {d["label"]: d for d in devices(client, auth, DEMO)}

    assert by_label["Ella's iPad"]["kind"] == "tablet"
    assert by_label["Work Laptop"]["kind"] == "laptop"
    assert by_label["Living Room TV"]["kind"] == "tv"


def test_devices_name_the_access_point_they_are_on(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    by_label = {d["label"]: d for d in devices(client, auth, DEMO)}

    assert by_label["Ella's iPad"]["ap_label"] == "Upstairs Extender"
    assert by_label["Living Room TV"]["ap_label"] == "Living Room Hub"


def test_status_summary_is_speakable_and_healthy_at_baseline(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    for row in devices(client, auth, DEMO):
        assert row["status_summary"]
        assert row["status_summary"] == "good signal on the faster band"


def test_the_ipad_is_the_faulted_device_under_wifi_degraded(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """The complaint and the verdict must name the same device or the demo does not land."""
    by_label = {d["label"]: d for d in devices(client, auth, DEMO)}
    ipad = by_label["Ella's iPad"]

    assert ipad["band"] == "2.4"
    assert ipad["rssi"] == -78
    assert ipad["status_summary"] == "weak signal on the slower band"
    assert ipad["steer_eligible"] is True

    # And the diagnostic verdict names it too.
    verdict = client.get(
        "/gx/net-diagnostics", params={"identifier": DEMO}, headers=auth
    ).json()
    assert verdict["primary_target_label"] == "Ella's iPad"
    assert verdict["primary_target"] == ipad["device_id"]


def test_healthy_devices_sit_alongside_the_faulted_one(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """So "which device?" and a named-healthy-device answer are both meaningful."""
    rows = devices(client, auth, DEMO)
    healthy = [d for d in rows if d["status_summary"] == "good signal on the faster band"]

    assert len(healthy) >= 2


def test_weakest_device_leads(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    rows = devices(client, auth, DEMO)

    assert rows[0]["label"] == "Ella's iPad"
    assert [r["rssi"] for r in rows] == sorted(r["rssi"] for r in rows)


def test_unknown_identifier_is_an_empty_array_not_an_error(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    r = client.get("/gx/devices", params={"identifier": UNKNOWN}, headers=auth)

    assert r.status_code == 200
    assert r.json() == []


def test_subscriber_without_a_network_is_an_empty_array(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert devices(client, auth, NO_NETWORK) == []


def test_unparseable_identifier_is_an_empty_array(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    assert devices(client, auth, "???") == []


def test_normalizes_the_identifier(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    for spelling in (" 447700900000", "07700900000"):
        assert len(devices(client, auth, spelling)) == 4


def test_cross_tenant_lookup_does_not_leak(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    body = devices(client, {**auth, "X-Tenant": "acme"}, DEMO)

    assert body == []


def test_each_tenant_sees_its_own_devices(
    client: TestClient, auth: dict[str, str], seeded_northwind: None, seeded_acme: None
) -> None:
    acme = devices(client, {**auth, "X-Tenant": "acme"}, ACME_PHONE)

    assert {d["label"] for d in acme} == {"Acme Phone"}
