"""Coverage on /gx/net-status and its consistency with /gx/offers, end to end.

The durability test is the important one: it drives the whole fix sequence and pins that
coverage does not flip to good when the fault clears — the entire point of BE-6.
"""

from fastapi.testclient import TestClient

DEMO = "+447700900000"
HEALTHY = "+447700900001"
UNKNOWN = "+447700900999"

FLAT_TYPES = (str, int, float, bool)


def status(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> dict:
    return client.get("/gx/net-status", params={"identifier": identifier}, headers=auth).json()


def diagnostics(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> dict:
    return client.get(
        "/gx/net-diagnostics", params={"identifier": identifier}, headers=auth
    ).json()


def offers(client: TestClient, auth: dict[str, str], identifier: str = DEMO) -> dict:
    return client.get("/gx/offers", params={"identifier": identifier}, headers=auth).json()


def act(client: TestClient, auth: dict[str, str], action: str, target: str) -> dict:
    return client.post(
        "/gx/device-action",
        json={"identifier": DEMO, "action": action, "target": target, "params": ""},
        headers=auth,
    ).json()


# ── the coverage fields on net-status ────────────────────────────────────────────────


def test_net_status_carries_flat_coverage_fields(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = status(client, auth)

    for key in ("coverage", "coverage_note", "coverage_device_count", "coverage_worst_area"):
        assert key in body
        assert isinstance(body[key], FLAT_TYPES)


def test_demo_reads_weak_with_a_cluster_at_healthy_baseline(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = status(client, auth)

    # Healthy AND weak coverage — the two ideas are separate.
    assert body["healthy"] is True
    assert body["fault_type"] == "none"
    assert body["coverage"] == "weak"
    assert body["coverage_device_count"] >= 2
    assert body["coverage_worst_area"] == "Upstairs Extender"
    assert "Upstairs Extender" in body["coverage_note"]


def test_healthy_subscriber_reads_good_and_is_not_offer_eligible(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = status(client, auth, HEALTHY)

    assert body["coverage"] == "good"
    assert body["coverage_note"] == ""
    assert body["coverage_device_count"] == 0
    assert body["coverage_worst_area"] == ""
    assert offers(client, auth, HEALTHY)["eligible"] is False


def test_unknown_subscriber_coverage_defaults(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    body = status(client, auth, UNKNOWN)

    assert body["found"] is False
    assert body["coverage"] == "good"
    assert body["coverage_device_count"] == 0


# ── the durability test (the important one) ──────────────────────────────────────────


def test_coverage_is_durable_across_the_full_self_heal(
    client: TestClient, auth: dict[str, str], staged_wifi_degraded: None
) -> None:
    """Apply the fault, run the whole fix sequence, and assert coverage stays weak and the
    offer stays eligible at every step, while fault_type ends at none. A reboot fixes
    stability, it does not move devices closer, so coverage must not flip to good."""

    def assert_weak_and_eligible(where: str) -> None:
        s = status(client, auth)
        assert s["coverage"] == "weak", f"{where}: coverage flipped to good"
        assert s["coverage_device_count"] >= 1, where
        assert offers(client, auth)["eligible"] is True, f"{where}: offer vanished"

    # 0. staged fault: band-stuck device, coverage already weak
    first = diagnostics(client, auth)
    assert first["fault_type"] == "device_band_stuck"
    assert_weak_and_eligible("after staging")

    # 1. band-steer clears the device fault; the extender fault surfaces next
    assert act(client, auth, "band-steer", first["primary_target"])["fault_cleared"] is True
    assert_weak_and_eligible("after band-steer")

    # 2. reboot the extender; the fault sequence completes
    second = diagnostics(client, auth)
    assert second["fault_type"] == "extender_flapping"
    assert act(client, auth, "reboot-extender", second["primary_target"])["fault_cleared"] is True

    # 3. no fault remains — but coverage is STILL weak and the offer STILL stands
    final = status(client, auth)
    assert final["fault_type"] == "none"
    assert final["healthy"] is True
    assert final["coverage"] == "weak"
    assert final["coverage_worst_area"] == "Upstairs Extender"
    assert offers(client, auth)["eligible"] is True


# ── single source of truth: coverage weak <=> offer eligible ─────────────────────────


def test_offer_eligibility_matches_coverage_for_the_demo_subscriber(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    s = status(client, auth, DEMO)
    o = offers(client, auth, DEMO)

    assert (s["coverage"] == "weak") == (o["eligible"] is True)


def test_offer_eligibility_matches_coverage_for_a_healthy_subscriber(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    s = status(client, auth, HEALTHY)
    o = offers(client, auth, HEALTHY)

    assert (s["coverage"] == "weak") == (o["eligible"] is True)


def test_offers_reason_is_the_coverage_note(
    client: TestClient, auth: dict[str, str], seeded_northwind: None
) -> None:
    """One signal, stated once: the reason the customer hears is the net-status note."""
    s = status(client, auth, DEMO)
    o = offers(client, auth, DEMO)

    assert o["eligible"] is True
    assert o["reason"] == s["coverage_note"]
