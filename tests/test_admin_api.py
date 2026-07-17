from fastapi.testclient import TestClient

ADMIN = ("admin", "test-admin-password")
DEMO_PHONE = "+447700900000"


def _row(client: TestClient, identifier: str = DEMO_PHONE) -> dict:
    subscribers = client.get("/admin/subscribers", auth=ADMIN).json()
    return next(s for s in subscribers if s["identifier"] == identifier)


# ── control surface ──────────────────────────────────────────────────────────────────


def test_scenarios_are_listed_from_the_packs(client: TestClient, seeded_northwind: None) -> None:
    body = client.get("/admin/scenarios", auth=ADMIN).json()

    names = {s["name"] for s in body}
    assert {"wifi_degraded", "outage_in_area", "healthy"} <= names

    wifi = next(s for s in body if s["name"] == "wifi_degraded")
    assert wifi["subscribers"] == [DEMO_PHONE]
    assert wifi["steps"] == 3
    assert wifi["reset_first"] is True
    assert wifi["description"]


def test_subscribers_report_baseline_health(client: TestClient, seeded_northwind: None) -> None:
    row = _row(client)

    assert row["display_name"]
    assert row["has_network"] is True
    assert row["healthy"] is True
    assert row["fault_type"] == "none"


def test_apply_then_subscribers_shows_the_fault(
    client: TestClient, seeded_northwind: None
) -> None:
    r = client.post("/admin/scenario/apply", json={"scenario": "wifi_degraded"}, auth=ADMIN)

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "apply"
    assert body["scenario"] == "wifi_degraded"
    assert body["rows_changed"] > 0

    row = _row(client)
    assert row["healthy"] is False
    assert row["fault_type"] == "device_band_stuck"
    assert row["recommended_action"] == "band-steer"
    assert row["extender_status"] == "flapping"


def test_reset_returns_to_baseline(client: TestClient, seeded_northwind: None) -> None:
    client.post("/admin/scenario/apply", json={"scenario": "wifi_degraded"}, auth=ADMIN)
    assert _row(client)["healthy"] is False

    r = client.post("/admin/scenario/reset", auth=ADMIN)

    assert r.status_code == 200
    assert r.json()["action"] == "reset"
    assert _row(client)["healthy"] is True


def test_unknown_scenario_is_404(client: TestClient, seeded_northwind: None) -> None:
    r = client.post("/admin/scenario/apply", json={"scenario": "nope"}, auth=ADMIN)

    assert r.status_code == 404


def test_events_are_exposed(client: TestClient, seeded_northwind: None) -> None:
    client.post("/admin/scenario/apply", json={"scenario": "wifi_degraded"}, auth=ADMIN)
    client.post("/admin/scenario/reset", auth=ADMIN)

    body = client.get("/admin/events", auth=ADMIN).json()

    assert [e["action"] for e in body] == ["reset", "apply"]  # newest first
    assert body[1]["scenario"] == "wifi_degraded"
    assert body[0]["created_at"]


def test_subscribers_without_a_network_are_marked(
    client: TestClient, seeded_northwind: None
) -> None:
    row = _row(client, "+447700900009")

    assert row["has_network"] is False
    assert row["fault_type"] == ""


def test_admin_is_tenant_scoped(
    client: TestClient, seeded_northwind: None, seeded_acme: None
) -> None:
    northwind = client.get("/admin/subscribers", auth=ADMIN).json()
    acme = client.get("/admin/subscribers", auth=ADMIN, headers={"X-Tenant": "acme"}).json()

    assert len(northwind) == 10
    assert len(acme) == 3
    assert {s["identifier"] for s in northwind}.isdisjoint({s["identifier"] for s in acme})


# ── the UI ───────────────────────────────────────────────────────────────────────────


def test_ui_renders_the_subscriber_list(client: TestClient, seeded_northwind: None) -> None:
    r = client.get("/admin/", auth=ADMIN)

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Backlot admin" in body
    assert "Northwind Mobile" in body
    assert DEMO_PHONE in body
    # The scenario buttons are rendered from the packs.
    assert "WiFi degraded" in body
    assert "Reset to baseline" in body


def test_ui_loads_htmx_locally_not_from_a_cdn(client: TestClient, seeded_northwind: None) -> None:
    body = client.get("/admin/", auth=ADMIN).text

    assert '/admin/static/htmx.min.js' in body
    assert "unpkg.com" not in body and "cdn." not in body

    assert client.get("/admin/static/htmx.min.js").status_code == 200


def test_ui_apply_swaps_in_the_changed_state(client: TestClient, seeded_northwind: None) -> None:
    r = client.post("/admin/ui/apply/wifi_degraded", auth=ADMIN)

    assert r.status_code == 200
    body = r.text
    # The fragment htmx swaps in, carrying the new state.
    assert 'id="state"' in body
    assert "device_band_stuck" in body
    assert "degraded" in body


def test_ui_reset_swaps_back_to_baseline(client: TestClient, seeded_northwind: None) -> None:
    client.post("/admin/ui/apply/wifi_degraded", auth=ADMIN)

    r = client.post("/admin/ui/reset", auth=ADMIN)

    assert r.status_code == 200
    assert "device_band_stuck" not in r.text
    assert "healthy" in r.text


def test_ui_shows_the_event_log(client: TestClient, seeded_northwind: None) -> None:
    client.post("/admin/ui/apply/wifi_degraded", auth=ADMIN)

    body = client.get("/admin/fragments/state", auth=ADMIN).text

    assert "Event log" in body
    assert "wifi_degraded" in body


def test_ui_reports_a_bad_scenario_without_a_500(
    client: TestClient, seeded_northwind: None
) -> None:
    r = client.post("/admin/ui/apply/does_not_exist", auth=ADMIN)

    assert r.status_code == 400
    assert "No scenario" in r.text


def test_docs_document_the_admin_control_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/admin/scenario/apply" in paths
    assert "/admin/scenario/reset" in paths
    assert "/admin/scenarios" in paths
    assert "/admin/subscribers" in paths
    # HTML fragments stay out of the schema: they are not a contract.
    assert "/admin/ui/reset" not in paths
