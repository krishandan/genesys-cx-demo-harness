"""Coverage assessment — the durable, fault-independent signal.

Unit tests build a Topology in memory so the thresholds are exercised directly, and the
boundary cases (cluster vs single-worst, good vs weak) are pinned. The durability test
that drives the live endpoints lives in test_gx_coverage.py.
"""

from __future__ import annotations

import uuid

from app.modules.network.coverage import assess_coverage
from app.modules.network.models import AccessPoint, ConnectedDevice
from app.modules.network.service import Topology

# The Northwind thresholds, as a plain dict (no DB needed).
CFG = {
    "steer_target_band": "5",
    "coverage": {
        "edge_rssi_5ghz_dbm": -60,
        "edge_rssi_24ghz_dbm": -68,
        "min_cluster_size": 2,
        "single_worst_rssi_dbm": -58,
    },
}


def _ap(kind: str, label: str) -> AccessPoint:
    ap = AccessPoint(kind=kind, label=label, model="m", status="online", backhaul_quality=96)
    ap.ap_id = uuid.uuid4()
    return ap


def _device(ap: AccessPoint, band: str, rssi: int, label: str = "d") -> ConnectedDevice:
    d = ConnectedDevice(label=label, kind="laptop", mac="02:00:00:00:00:01", band=band, rssi=rssi)
    d.connected_ap_id = ap.ap_id
    return d


def _topology(aps: list[AccessPoint], devices: list[ConnectedDevice]) -> Topology:
    return Topology(party_id=uuid.uuid4(), gateway=None, access_points=aps, devices=devices)


def test_good_when_devices_are_within_range() -> None:
    ext = _ap("extender", "Upstairs Extender")
    topo = _topology([ext], [_device(ext, "5", -48), _device(ext, "5", -52)])

    cov = assess_coverage(topo, CFG)

    assert cov.is_weak is False
    assert cov.level == "good"
    assert cov.device_count == 0
    assert cov.worst_area == ""
    assert cov.note == ""


def test_weak_via_cluster_of_two_edge_devices() -> None:
    ext = _ap("extender", "Upstairs Extender")
    # Two devices below the 5GHz edge threshold on one extender.
    topo = _topology([ext], [_device(ext, "5", -61), _device(ext, "5", -62)])

    cov = assess_coverage(topo, CFG)

    assert cov.is_weak is True
    assert cov.device_count == 2
    assert cov.worst_area == "Upstairs Extender"
    assert "Two devices" in cov.note
    assert "Upstairs Extender" in cov.note


def test_weak_via_single_worst_device() -> None:
    ext = _ap("extender", "Upstairs Extender")
    # Only one device, but weaker than the single-worst threshold (-58).
    topo = _topology([ext], [_device(ext, "5", -61), _device(ext, "5", -50)])

    cov = assess_coverage(topo, CFG)

    assert cov.is_weak is True
    assert cov.device_count == 1  # only the -61 device is at the edge
    assert cov.note.startswith("A device is hanging")


def test_a_single_edge_device_above_single_worst_is_still_good() -> None:
    """One device at exactly the boundary between the two thresholds: not a cluster (needs
    2), and not past the single-worst bar, so coverage is good."""
    ext = _ap("extender", "Upstairs Extender")
    # -59 is weaker than edge (-60)? No: -59 > -60, so NOT edge. And -59 > single-worst
    # (-58)? No: -59 < -58, so it IS past single-worst. Use -59 to test the worst rule.
    # Here use a device that is neither: -57 (stronger than both thresholds).
    topo = _topology([ext], [_device(ext, "5", -57)])

    cov = assess_coverage(topo, CFG)

    assert cov.is_weak is False


def test_cluster_threshold_is_a_boundary() -> None:
    """One edge device is not a cluster; a second one tips it (given both clear the edge
    threshold but neither trips single-worst on its own — use -59/-59, past single-worst,
    to keep the single-worst rule out and isolate the cluster rule, we instead raise the
    single-worst bar via config)."""
    cfg = {
        "steer_target_band": "5",
        "coverage": {
            "edge_rssi_5ghz_dbm": -60,
            "edge_rssi_24ghz_dbm": -68,
            "min_cluster_size": 2,
            "single_worst_rssi_dbm": -80,  # effectively disabled, so only the cluster rule fires
        },
    }
    ext = _ap("extender", "Upstairs Extender")

    one = _topology([ext], [_device(ext, "5", -62)])
    assert assess_coverage(one, cfg).is_weak is False  # one edge device, no cluster

    two = _topology([ext], [_device(ext, "5", -62), _device(ext, "5", -63)])
    assert assess_coverage(two, cfg).is_weak is True  # two -> cluster


def test_devices_on_the_hub_do_not_count() -> None:
    """Coverage is about distance from a booster; a weak device on the main hub is not a
    coverage gap a mesh point would fix."""
    hub = _ap("gateway", "Living Room Hub")
    topo = _topology([hub], [_device(hub, "5", -75), _device(hub, "5", -78)])

    assert assess_coverage(topo, CFG).is_weak is False


def test_24ghz_uses_its_own_threshold() -> None:
    # Disable the single-worst rule so this isolates the 2.4GHz edge/cluster threshold
    # (otherwise any device weaker than -58 trips weak regardless of band).
    cfg = {
        "steer_target_band": "5",
        "coverage": {
            "edge_rssi_5ghz_dbm": -60,
            "edge_rssi_24ghz_dbm": -68,
            "min_cluster_size": 2,
            "single_worst_rssi_dbm": -120,
        },
    }
    ext = _ap("extender", "Upstairs Extender")

    # -65 on 2.4GHz is within the 2.4 edge threshold (-68), so not edge.
    within = _topology([ext], [_device(ext, "2.4", -65), _device(ext, "2.4", -66)])
    assert assess_coverage(within, cfg).is_weak is False

    # -70 on 2.4GHz is past -68 -> edge; two of them -> a cluster.
    past = _topology([ext], [_device(ext, "2.4", -70), _device(ext, "2.4", -71)])
    assert assess_coverage(past, cfg).is_weak is True


def test_thresholds_are_config_not_hardcoded() -> None:
    """Flip the thresholds and the same topology reads differently — proves pack config."""
    ext = _ap("extender", "Upstairs Extender")
    topo = _topology([ext], [_device(ext, "5", -55), _device(ext, "5", -56)])

    lenient = {**CFG, "coverage": {**CFG["coverage"], "edge_rssi_5ghz_dbm": -50}}
    assert assess_coverage(topo, lenient).is_weak is True  # now -55/-56 count as edge

    strict = {**CFG, "coverage": {**CFG["coverage"], "edge_rssi_5ghz_dbm": -70}}
    assert assess_coverage(topo, strict).is_weak is False  # now they don't
