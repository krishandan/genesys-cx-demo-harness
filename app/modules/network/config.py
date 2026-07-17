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
    # recommended_actions is a mapping, so merge it rather than replace it wholesale.
    merged["recommended_actions"] = {
        **DEFAULTS["recommended_actions"],
        **(override.get("recommended_actions") or {}),
    }
    return merged
