"""Offer catalogue and eligibility.

Eligibility is derived from the subscriber's actual seeded topology — never from a
hardcoded subscriber id. Each condition in an offer's `eligibility` map is a registered
predicate; all of them must hold (AND). Adding an *offer* is a pack edit; adding a new
*kind* of condition is a new predicate here, which is a genuinely new capability.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.models import Tenant
from app.modules.network.models import AccessPoint, ConnectedDevice
from app.modules.network.service import Topology

EXTENDER_KIND = "extender"


@dataclass(frozen=True)
class Offer:
    offer_id: str
    name: str
    price_gbp: float
    reason: str
    eta_text: str
    eligibility: dict[str, Any] = field(default_factory=dict)


class UnknownEligibilityRule(KeyError):
    """A pack named a condition with no registered predicate."""


Predicate = Callable[[Topology, Any], bool]

PREDICATES: dict[str, Predicate] = {}


def predicate(name: str) -> Callable[[Predicate], Predicate]:
    def register(fn: Predicate) -> Predicate:
        PREDICATES[name] = fn
        return fn

    return register


def _extenders(topology: Topology) -> list[AccessPoint]:
    return [ap for ap in topology.access_points if ap.kind == EXTENDER_KIND]


def _devices_on_extenders(topology: Topology) -> list[ConnectedDevice]:
    extender_ids = {ap.ap_id for ap in _extenders(topology)}
    return [d for d in topology.devices if d.connected_ap_id in extender_ids]


@predicate("device_on_extender_rssi_at_or_below")
def _device_on_extender_rssi_at_or_below(topology: Topology, value: Any) -> bool:
    """A device hanging off a booster is at the edge of its range.

    Deliberately durable: rebooting the booster does not move a device's signal, so this
    stays true after a self-heal — the coverage gap is a property of the home, not of a
    transient fault.
    """
    return any(d.rssi <= int(value) for d in _devices_on_extenders(topology))


@predicate("any_device_rssi_at_or_below")
def _any_device_rssi_at_or_below(topology: Topology, value: Any) -> bool:
    return any(d.rssi <= int(value) for d in topology.devices)


@predicate("extender_backhaul_at_or_below")
def _extender_backhaul_at_or_below(topology: Topology, value: Any) -> bool:
    return any(ap.backhaul_quality <= int(value) for ap in _extenders(topology))


@predicate("extender_status_in")
def _extender_status_in(topology: Topology, value: Any) -> bool:
    wanted = {str(v) for v in value}
    return any(ap.status in wanted for ap in _extenders(topology))


@predicate("min_extenders")
def _min_extenders(topology: Topology, value: Any) -> bool:
    return len(_extenders(topology)) >= int(value)


@predicate("min_devices")
def _min_devices(topology: Topology, value: Any) -> bool:
    return len(topology.devices) >= int(value)


def offers_config(tenant: Tenant) -> dict[str, Any]:
    cfg = tenant.config_json.get("offers") or {}
    return dict(cfg)


def catalogue(tenant: Tenant) -> list[Offer]:
    """The tenant's offers, in pack order. Order is priority: the first eligible wins."""
    cfg = offers_config(tenant)
    default_eta = str(cfg.get("default_eta_text", ""))

    offers = []
    for raw in cfg.get("catalogue", []) or []:
        offers.append(
            Offer(
                offer_id=str(raw["offer_id"]),
                name=str(raw["name"]),
                price_gbp=float(raw["price_gbp"]),
                reason=str(raw.get("reason", "")),
                eta_text=str(raw.get("eta_text", default_eta)),
                eligibility=dict(raw.get("eligibility") or {}),
            )
        )
    return offers


def is_eligible(offer: Offer, topology: Topology) -> bool:
    """Every condition must hold. An offer with no conditions is always eligible."""
    for rule, value in offer.eligibility.items():
        check = PREDICATES.get(rule)
        if check is None:
            raise UnknownEligibilityRule(
                f"Offer '{offer.offer_id}' uses unknown eligibility rule '{rule}'. "
                f"Known rules: {', '.join(sorted(PREDICATES))}"
            )
        if not check(topology, value):
            return False
    return True


def best_offer(tenant: Tenant, topology: Topology) -> Offer | None:
    """The single best eligible offer, or None. Pack order is priority."""
    for offer in catalogue(tenant):
        if is_eligible(offer, topology):
            return offer
    return None


def find_offer(tenant: Tenant, offer_id: str) -> Offer | None:
    return next((o for o in catalogue(tenant) if o.offer_id == offer_id), None)
