"""Fault detection unit tests. No database: detectors are pure over a Topology."""

import uuid
from typing import Any

import pytest

from app.core.models import Tenant
from app.modules.network.config import DEFAULTS, network_config
from app.modules.network.faults import NO_FAULT, build_verdict, detect_all
from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway, Radio
from app.modules.network.service import Topology

TENANT_ID = uuid.uuid4()
PARTY_ID = uuid.uuid4()


def _ap(
    *,
    kind: str = "extender",
    status: str = "online",
    backhaul: int = 95,
    bands: tuple[str, ...] = ("2.4", "5"),
    label: str = "Extender",
) -> AccessPoint:
    ap = AccessPoint(
        ap_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        party_id=PARTY_ID,
        label=label,
        kind=kind,
        model="Test AP",
        status=status,
        backhaul_quality=backhaul,
    )
    ap.radios = [
        Radio(
            radio_id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            party_id=PARTY_ID,
            ap_id=ap.ap_id,
            band=b,
            channel=1,
            utilization=10,
        )
        for b in bands
    ]
    return ap


def _device(
    ap: AccessPoint,
    *,
    band: str = "2.4",
    rssi: int = -78,
    steer_eligible: bool = True,
    label: str = "Phone",
) -> ConnectedDevice:
    return ConnectedDevice(
        device_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        party_id=PARTY_ID,
        connected_ap_id=ap.ap_id,
        label=label,
        mac="02:00:00:00:00:01",
        band=band,
        rssi=rssi,
        steer_eligible=steer_eligible,
    )


def _gateway(wan_status: str = "online") -> Gateway:
    return Gateway(
        gateway_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        party_id=PARTY_ID,
        model="Test Hub",
        wan_status=wan_status,
        uptime_s=100,
    )


def _topology(
    *, gateway: Gateway | None = None, aps: list[AccessPoint], devices: list[ConnectedDevice]
) -> Topology:
    return Topology(
        party_id=PARTY_ID,
        gateway=gateway if gateway is not None else _gateway(),
        access_points=aps,
        devices=devices,
    )


CFG: dict[str, Any] = DEFAULTS


def test_healthy_network_has_no_fault() -> None:
    hub = _ap(kind="gateway", label="Hub")
    topology = _topology(aps=[hub], devices=[_device(hub, band="5", rssi=-48)])

    verdict = build_verdict(topology, CFG)

    assert verdict.fault_type == NO_FAULT
    assert verdict.recommended_action == "none"
    assert verdict.primary_target == ""
    assert verdict.wan_ok is True


def test_device_band_stuck_fires() -> None:
    hub = _ap(kind="gateway", label="Hub", bands=("2.4", "5"))
    phone = _device(hub, band="2.4", rssi=-78, steer_eligible=True)
    topology = _topology(aps=[hub], devices=[phone])

    verdict = build_verdict(topology, CFG)

    assert verdict.fault_type == "device_band_stuck"
    assert verdict.primary_target == str(phone.device_id)
    assert verdict.primary_target_kind == "device"
    assert verdict.recommended_action == "band-steer"


def test_device_is_not_stuck_when_signal_is_fine() -> None:
    hub = _ap(kind="gateway", bands=("2.4", "5"))
    topology = _topology(aps=[hub], devices=[_device(hub, band="2.4", rssi=-50)])

    assert build_verdict(topology, CFG).fault_type == NO_FAULT


def test_device_is_not_stuck_when_not_steer_eligible() -> None:
    hub = _ap(kind="gateway", bands=("2.4", "5"))
    topology = _topology(aps=[hub], devices=[_device(hub, rssi=-80, steer_eligible=False)])

    assert build_verdict(topology, CFG).fault_type == NO_FAULT


def test_device_is_not_stuck_when_there_is_nowhere_better_to_go() -> None:
    """A 2.4-only AP means a poor signal is not a band problem."""
    hub = _ap(kind="gateway", bands=("2.4",))
    topology = _topology(aps=[hub], devices=[_device(hub, band="2.4", rssi=-80)])

    assert build_verdict(topology, CFG).fault_type == NO_FAULT


def test_worst_stuck_device_is_the_target() -> None:
    hub = _ap(kind="gateway", bands=("2.4", "5"))
    mild = _device(hub, rssi=-72, label="Tablet")
    worst = _device(hub, rssi=-85, label="Phone")
    topology = _topology(aps=[hub], devices=[mild, worst])

    verdict = build_verdict(topology, CFG)

    assert verdict.primary_target == str(worst.device_id)
    assert verdict.primary_target_label == "Phone"


def test_extender_flapping_fires() -> None:
    hub = _ap(kind="gateway", label="Hub")
    ext = _ap(kind="extender", status="flapping", backhaul=34, label="Upstairs Extender")
    topology = _topology(aps=[hub, ext], devices=[])

    verdict = build_verdict(topology, CFG)

    assert verdict.fault_type == "extender_flapping"
    assert verdict.primary_target == str(ext.ap_id)
    assert verdict.primary_target_kind == "ap"
    assert verdict.recommended_action == "reboot-extender"
    assert verdict.extender_status == "flapping"


def test_extender_with_poor_backhaul_is_flapping_even_if_online() -> None:
    hub = _ap(kind="gateway", label="Hub")
    ext = _ap(kind="extender", status="online", backhaul=20)
    topology = _topology(aps=[hub, ext], devices=[])

    assert build_verdict(topology, CFG).fault_type == "extender_flapping"


def test_wan_degraded_fires_and_outranks_the_rest() -> None:
    hub = _ap(kind="gateway", label="Hub", bands=("2.4", "5"))
    ext = _ap(kind="extender", status="flapping", backhaul=20)
    topology = _topology(
        gateway=_gateway("degraded"), aps=[hub, ext], devices=[_device(hub, rssi=-85)]
    )

    verdict = build_verdict(topology, CFG)

    assert verdict.fault_type == "wan_degraded"
    assert verdict.primary_target_kind == "gateway"
    assert verdict.wan_ok is False
    assert verdict.recommended_action == "escalate"


def test_band_stuck_outranks_extender_flapping() -> None:
    """Least disruptive remedy first: this ordering is what makes the demo run
    band-steer before reboot-extender."""
    hub = _ap(kind="gateway", label="Hub", bands=("2.4", "5"))
    ext = _ap(kind="extender", status="flapping", backhaul=34)
    topology = _topology(aps=[hub, ext], devices=[_device(hub, rssi=-78)])

    verdict = build_verdict(topology, CFG)

    assert verdict.fault_type == "device_band_stuck"
    # But the extender problem is still visible in the flat verdict.
    assert verdict.extender_status == "flapping"
    assert set(detect_all(topology, CFG)) == {"device_band_stuck", "extender_flapping"}


def test_precedence_is_config_not_hardcoded() -> None:
    hub = _ap(kind="gateway", label="Hub", bands=("2.4", "5"))
    ext = _ap(kind="extender", status="flapping", backhaul=34)
    topology = _topology(aps=[hub, ext], devices=[_device(hub, rssi=-78)])

    flipped = {**CFG, "fault_precedence": ["extender_flapping", "device_band_stuck"]}

    assert build_verdict(topology, flipped).fault_type == "extender_flapping"


def test_poor_rssi_threshold_is_config() -> None:
    hub = _ap(kind="gateway", bands=("2.4", "5"))
    topology = _topology(aps=[hub], devices=[_device(hub, band="2.4", rssi=-60)])

    assert build_verdict(topology, CFG).fault_type == NO_FAULT
    lenient = {**CFG, "poor_rssi_dbm": -50}
    assert build_verdict(topology, lenient).fault_type == "device_band_stuck"


def test_extender_status_is_none_when_there_are_no_extenders() -> None:
    hub = _ap(kind="gateway", label="Hub")

    assert build_verdict(_topology(aps=[hub], devices=[]), CFG).extender_status == "none"


def test_worst_device_fields_reflect_the_weakest_signal() -> None:
    hub = _ap(kind="gateway", bands=("2.4", "5"))
    topology = _topology(
        aps=[hub],
        devices=[_device(hub, band="5", rssi=-50, steer_eligible=False), _device(hub, rssi=-78)],
    )

    verdict = build_verdict(topology, CFG)

    assert verdict.worst_device_rssi == -78
    assert verdict.worst_device_band == "2.4"


@pytest.mark.parametrize("wan_status", ["degraded", "offline"])
def test_any_non_ok_wan_status_is_a_fault(wan_status: str) -> None:
    hub = _ap(kind="gateway", label="Hub")
    topology = _topology(gateway=_gateway(wan_status), aps=[hub], devices=[])

    assert build_verdict(topology, CFG).fault_type == "wan_degraded"


def test_tenant_config_overrides_module_defaults() -> None:
    tenant = Tenant(
        tenant_id=TENANT_ID,
        slug="t",
        display_name="T",
        industry="telco",
        branding_json={},
        config_json={"network": {"poor_rssi_dbm": -50}},
    )

    cfg = network_config(tenant)

    assert cfg["poor_rssi_dbm"] == -50
    # Untouched defaults survive the merge.
    assert cfg["steer_target_band"] == DEFAULTS["steer_target_band"]
    assert cfg["recommended_actions"]["device_band_stuck"] == "band-steer"


def test_tenant_can_override_one_recommended_action_without_losing_the_rest() -> None:
    tenant = Tenant(
        tenant_id=TENANT_ID,
        slug="t",
        display_name="T",
        industry="telco",
        branding_json={},
        config_json={"network": {"recommended_actions": {"wan_degraded": "send-engineer"}}},
    )

    cfg = network_config(tenant)

    assert cfg["recommended_actions"]["wan_degraded"] == "send-engineer"
    assert cfg["recommended_actions"]["device_band_stuck"] == "band-steer"
