from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Tenant
from app.modules.network.config import network_config
from app.modules.network.faults import NO_FAULT, build_verdict
from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway
from app.modules.network.service import load_topology
from app.scenarios.engine import (
    ScenarioError,
    ScenarioNotFoundError,
    apply,
    list_scenarios,
    load_scenario,
    recent_events,
    reset,
)
from app.scenarios.models import ScenarioEvent

DEMO_PHONE = "+447700900000"


def _fault(db: Session, tenant: Tenant) -> str:
    party_id = _demo_party_id(db, tenant)
    topology = load_topology(db, tenant, party_id)
    return build_verdict(topology, network_config(tenant)).fault_type


def _demo_party_id(db: Session, tenant: Tenant):
    from app.core.models import Identity

    return db.execute(
        select(Identity.party_id).where(
            Identity.tenant_id == tenant.tenant_id, Identity.value == DEMO_PHONE
        )
    ).scalar_one()


def _phone(db: Session, tenant: Tenant) -> ConnectedDevice:
    return db.execute(
        select(ConnectedDevice).where(
            ConnectedDevice.tenant_id == tenant.tenant_id,
            ConnectedDevice.seed_key == "phone",
            ConnectedDevice.party_id == _demo_party_id(db, tenant),
        )
    ).scalar_one()


# ── packs ────────────────────────────────────────────────────────────────────────────


def test_the_required_scenarios_exist(db: Session) -> None:
    names = {s.name for s in list_scenarios("northwind")}

    assert {"wifi_degraded", "outage_in_area", "healthy"} <= names


def test_a_scenario_is_a_file_not_code(db: Session, tmp_path: Path) -> None:
    """Adding a scenario must be a new YAML file. Nothing is registered in code."""
    (tmp_path / "northwind").mkdir()
    (tmp_path / "northwind" / "brand_new.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "brand_new",
                "subscribers": {"identifiers": [DEMO_PHONE]},
                "steps": [
                    {"entity": "gateway", "match": {"seed_key": "gateway"}, "set": {"uptime_s": 7}}
                ],
            }
        )
    )

    scenario = load_scenario("northwind", "brand_new", packs_dir=tmp_path)

    assert scenario.name == "brand_new"
    assert len(scenario.steps) == 1


def test_unknown_scenario_raises_not_found(db: Session) -> None:
    with pytest.raises(ScenarioNotFoundError, match="No scenario"):
        load_scenario("northwind", "does_not_exist")


def test_a_scenario_cannot_name_an_unknown_entity(tmp_path: Path) -> None:
    (tmp_path / "northwind").mkdir()
    (tmp_path / "northwind" / "bad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "bad",
                "subscribers": {"identifiers": [DEMO_PHONE]},
                "steps": [{"entity": "unicorn", "match": {}, "set": {"x": 1}}],
            }
        )
    )

    with pytest.raises(ScenarioError, match="unknown entity"):
        load_scenario("northwind", "bad", packs_dir=tmp_path)


def test_a_scenario_cannot_set_a_protected_field(tmp_path: Path) -> None:
    """Setting tenant_id would let a scenario re-parent a row across tenants."""
    (tmp_path / "northwind").mkdir()
    (tmp_path / "northwind" / "evil.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "evil",
                "subscribers": {"identifiers": [DEMO_PHONE]},
                "steps": [
                    {
                        "entity": "connected_device",
                        "match": {"seed_key": "phone"},
                        "set": {"tenant_id": "00000000-0000-0000-0000-000000000000"},
                    }
                ],
            }
        )
    )

    with pytest.raises(ScenarioError, match="cannot be set"):
        load_scenario("northwind", "evil", packs_dir=tmp_path)


def test_a_scenario_cannot_match_a_field_that_does_not_exist(tmp_path: Path) -> None:
    (tmp_path / "northwind").mkdir()
    (tmp_path / "northwind" / "typo.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "typo",
                "subscribers": {"identifiers": [DEMO_PHONE]},
                "steps": [
                    {
                        "entity": "access_point",
                        "match": {"knid": "extender"},
                        "set": {"status": "online"},
                    }
                ],
            }
        )
    )

    with pytest.raises(ScenarioError, match="no field"):
        load_scenario("northwind", "typo", packs_dir=tmp_path)


# ── apply / reset ────────────────────────────────────────────────────────────────────


def test_baseline_is_healthy(db: Session, northwind: Tenant) -> None:
    assert _fault(db, northwind) == NO_FAULT


def test_apply_wifi_degraded_stages_the_demo_fault(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "wifi_degraded")

    # Band-stuck first, per fault_precedence. That is the demo's opening move.
    assert _fault(db, northwind) == "device_band_stuck"

    phone = _phone(db, northwind)
    assert phone.band == "2.4"
    assert phone.rssi == -78


def test_reset_restores_the_baseline(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "wifi_degraded")
    assert _fault(db, northwind) == "device_band_stuck"

    reset(db, northwind)

    assert _fault(db, northwind) == NO_FAULT
    phone = _phone(db, northwind)
    assert phone.band == "5"
    assert phone.rssi == -48


def test_apply_is_idempotent(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "wifi_degraded")
    first = _fault(db, northwind)

    apply(db, northwind, "wifi_degraded")

    assert _fault(db, northwind) == first == "device_band_stuck"


def test_reset_is_idempotent(db: Session, northwind: Tenant) -> None:
    reset(db, northwind)
    reset(db, northwind)

    assert _fault(db, northwind) == NO_FAULT


def test_apply_recovers_from_a_half_healed_state(db: Session, northwind: Tenant) -> None:
    """reset_first means a re-apply does not depend on what the last take left behind."""
    apply(db, northwind, "wifi_degraded")

    # Simulate the operator having run only half the demo.
    phone = _phone(db, northwind)
    phone.band = "5"
    phone.rssi = -56
    db.add(phone)
    db.commit()

    apply(db, northwind, "wifi_degraded")

    assert _fault(db, northwind) == "device_band_stuck"


def test_outage_in_area_outranks_the_in_home_faults(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "outage_in_area")

    assert _fault(db, northwind) == "wan_degraded"

    party_id = _demo_party_id(db, northwind)
    topology = load_topology(db, northwind, party_id)
    verdict = build_verdict(topology, network_config(northwind))
    assert verdict.recommended_action == "escalate"


def test_healthy_scenario_heals_the_subscriber(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "wifi_degraded")
    assert _fault(db, northwind) != NO_FAULT

    apply(db, northwind, "healthy")

    assert _fault(db, northwind) == NO_FAULT


def test_scenarios_do_not_create_or_delete_rows(db: Session, northwind: Tenant) -> None:
    def counts() -> tuple[int, ...]:
        return (
            len(db.execute(select(Gateway)).scalars().all()),
            len(db.execute(select(AccessPoint)).scalars().all()),
            len(db.execute(select(ConnectedDevice)).scalars().all()),
        )

    before = counts()
    apply(db, northwind, "wifi_degraded")
    apply(db, northwind, "outage_in_area")
    reset(db, northwind)

    assert counts() == before


# ── the requirement that defines the phase ───────────────────────────────────────────


def test_the_demo_runs_repeatedly_with_no_reseed(db: Session, northwind: Tenant) -> None:
    """Stage, walk the fixes, reset, repeat — three times, no `make seed` anywhere.

    This is the acceptance bar: everything else is the means to it.
    """
    from app.modules.network.actions import band_steer, reboot_extender

    cfg = network_config(northwind)
    party_id = _demo_party_id(db, northwind)

    for take in range(3):
        apply(db, northwind, "wifi_degraded")
        assert _fault(db, northwind) == "device_band_stuck", f"take {take}: fault not staged"

        # Walk the fixes exactly as the gx verbs would.
        topology = load_topology(db, northwind, party_id)
        verdict = build_verdict(topology, cfg)
        assert band_steer(db, topology, verdict.primary_target, {}, cfg).ok
        db.commit()

        topology = load_topology(db, northwind, party_id)
        verdict = build_verdict(topology, cfg)
        assert verdict.fault_type == "extender_flapping", f"take {take}: extender fault missing"
        assert reboot_extender(db, topology, verdict.primary_target, {}, cfg).ok
        db.commit()

        assert _fault(db, northwind) == NO_FAULT, f"take {take}: did not heal"

        reset(db, northwind)
        assert _fault(db, northwind) == NO_FAULT, f"take {take}: reset left a fault"


# ── event log ────────────────────────────────────────────────────────────────────────


def test_apply_and_reset_are_logged(db: Session, northwind: Tenant) -> None:
    apply(db, northwind, "wifi_degraded")
    reset(db, northwind)

    events = recent_events(db, northwind)

    assert len(events) == 2
    actions = {e.action for e in events}
    assert actions == {"apply", "reset"}
    applied = next(e for e in events if e.action == "apply")
    assert applied.scenario == "wifi_degraded"
    assert applied.rows_changed > 0
    assert applied.summary


def test_apply_with_reset_first_logs_one_event_not_two(db: Session, northwind: Tenant) -> None:
    """The internal reset is an implementation detail of apply, not an operator action."""
    apply(db, northwind, "wifi_degraded")

    events = recent_events(db, northwind)

    assert [e.action for e in events] == ["apply"]


# ── tenant isolation ─────────────────────────────────────────────────────────────────


def test_apply_never_touches_another_tenant(
    db: Session, northwind: Tenant, seeded_acme: None
) -> None:
    acme = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()
    before = {
        (d.device_id, d.band, d.rssi)
        for d in db.execute(
            select(ConnectedDevice).where(ConnectedDevice.tenant_id == acme.tenant_id)
        ).scalars()
    }

    apply(db, northwind, "wifi_degraded")

    after = {
        (d.device_id, d.band, d.rssi)
        for d in db.execute(
            select(ConnectedDevice).where(ConnectedDevice.tenant_id == acme.tenant_id)
        ).scalars()
    }
    assert after == before


def test_reset_never_touches_another_tenant(
    db: Session, northwind: Tenant, seeded_acme: None
) -> None:
    acme = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()

    # Acme's own seeded state is degraded; northwind's reset must not heal it.
    acme_before = {
        (ap.ap_id, ap.status, ap.backhaul_quality)
        for ap in db.execute(
            select(AccessPoint).where(AccessPoint.tenant_id == acme.tenant_id)
        ).scalars()
    }

    reset(db, northwind)

    acme_after = {
        (ap.ap_id, ap.status, ap.backhaul_quality)
        for ap in db.execute(
            select(AccessPoint).where(AccessPoint.tenant_id == acme.tenant_id)
        ).scalars()
    }
    assert acme_after == acme_before


def test_events_are_tenant_scoped(db: Session, northwind: Tenant, seeded_acme: None) -> None:
    acme = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()

    apply(db, northwind, "wifi_degraded")

    assert len(recent_events(db, northwind)) == 1
    assert recent_events(db, acme) == []
    assert (
        len(db.execute(select(ScenarioEvent)).scalars().all()) == 1
    ), "an event leaked across tenants"


def test_a_scenario_naming_another_tenants_subscriber_changes_nothing(
    db: Session, seeded_acme: None, tmp_path: Path
) -> None:
    """An identifier that belongs to northwind must not resolve while scoped to acme."""
    acme = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "reach_over.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "reach_over",
                "subscribers": {"identifiers": [DEMO_PHONE]},  # a northwind number
                "steps": [
                    {
                        "entity": "connected_device",
                        "match": {"seed_key": "phone"},
                        "set": {"rssi": -99},
                    }
                ],
            }
        )
    )

    with pytest.raises(ScenarioError, match="resolve"):
        apply(db, acme, "reach_over", packs_dir=tmp_path)
