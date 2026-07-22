"""Network module config.

Defaults live here; a tenant overrides any of them under `config_json.network` in its
pack. No threshold in this module is a magic number at a call site.
"""

from typing import Any

from app.core.models import Tenant

DEFAULTS: dict[str, Any] = {
    # A steer-eligible device at or below this rssi is badly placed on its band.
    "poor_rssi_dbm": -70,
    # The band we steer devices onto, and what a good rssi looks like once there.
    "steer_target_band": "5",
    "steer_rssi_gain_db": 22,
    "steer_rssi_ceiling_dbm": -45,
    # An AP in one of these states is not carrying traffic reliably.
    "flapping_ap_statuses": ["flapping", "offline"],
    # Backhaul at or below this is degraded even if the AP claims to be online.
    "poor_backhaul_quality": 40,
    "healthy_backhaul_quality": 92,
    # WAN is fine only in these states.
    "wan_ok_statuses": ["online"],
    # Coverage weakness — a DURABLE, fault-independent property of the home. A device far
    # from any hub sits at the edge of range; a reboot or band-steer does not move it
    # closer, so this must not change when a fault clears. Keyed off distance (extender +
    # rssi), never off fault state. Every threshold here is pack config.
    "coverage": {
        # A device on an extender weaker than this, on the fast band, is at the edge.
        "edge_rssi_5ghz_dbm": -60,
        # 2.4GHz reaches further, so "edge" there is a weaker number.
        "edge_rssi_24ghz_dbm": -68,
        # This many edge-of-range devices on one extender => a coverage cluster => weak.
        "min_cluster_size": 2,
        # A single device on an extender weaker than this is enough on its own => weak.
        "single_worst_rssi_dbm": -58,
    },
    # Which fault wins when several fire at once. Least disruptive remedy first:
    # a band steer is instant and invisible, rebooting an extender drops it.
    "fault_precedence": ["wan_degraded", "device_band_stuck", "extender_flapping"],
    # Verdict -> the verb AVA should call.
    "recommended_actions": {
        "wan_degraded": "escalate",
        "device_band_stuck": "band-steer",
        "extender_flapping": "reboot-extender",
        "none": "none",
    },
}


def network_config(tenant: Tenant) -> dict[str, Any]:
    """Module defaults with the tenant's pack overrides layered on top."""
    override = tenant.config_json.get("network") or {}
    merged = {**DEFAULTS, **override}
    # Nested mappings merge rather than replace wholesale, so a pack can override a single
    # threshold without restating the rest.
    merged["recommended_actions"] = {
        **DEFAULTS["recommended_actions"],
        **(override.get("recommended_actions") or {}),
    }
    merged["coverage"] = {
        **DEFAULTS["coverage"],
        **(override.get("coverage") or {}),
    }
    return merged
