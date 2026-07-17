"""The scenario engine.

A scenario is a YAML file of field-setters (match + set) over entities that already
exist. It never creates or deletes rows, and it never redefines fault detection — the
thresholds in config_json.network decide what a staged state *means*.

Two operations:

- `reset(tenant)` re-materializes the tenant's seeded baseline in place, from the seed
  pack. The pack is the single definition of the baseline, so reset cannot drift from
  it. No Faker, no spine writes, no full re-seed.
- `apply(tenant, name)` mutates to a named staged state.

Both are tenant-scoped: every statement filters on tenant_id, and a scenario can only
address parties it resolves within its own tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.models import Identity, Party, Tenant
from app.events.models import Event
from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway, Radio
from app.modules.network.telemetry import emit_network_telemetry
from app.scenarios.models import ScenarioEvent
from app.seed.generator import PACKS_DIR as SEED_PACKS_DIR
from app.seed.generator import _key, load_pack
from app.seed.network import SeedParty, seed_networks

PACKS_DIR = Path(__file__).parent / "packs"

# Entities a scenario may address, by the name used in YAML. Values are declarative
# models addressed dynamically by name, so this is Any rather than type[Base].
ENTITIES: dict[str, Any] = {
    "gateway": Gateway,
    "access_point": AccessPoint,
    "radio": Radio,
    "connected_device": ConnectedDevice,
}

# Never settable by a scenario: identity, ownership, and the seed's own handles.
# Excluding tenant_id/party_id is what stops a scenario re-parenting a row across
# tenants; excluding seed_key keeps a row's logical name stable for the next match.
PROTECTED_FIELDS = {"tenant_id", "party_id", "seed_key", "updated_at"}


class ScenarioError(Exception):
    """A scenario pack is malformed or names something that does not exist."""


class ScenarioNotFoundError(ScenarioError):
    pass


@dataclass(frozen=True)
class ScenarioStep:
    entity: str
    match: dict[str, Any]
    set_fields: dict[str, Any]
    description: str = ""


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    reset_first: bool
    identifiers: list[str]
    steps: list[ScenarioStep] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioResult:
    action: str
    scenario: str
    rows_changed: int
    summary: str


def _model_columns(model: Any) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _settable(model: Any) -> set[str]:
    pk = {c.name for c in model.__table__.primary_key.columns}
    fks = {c.name for c in model.__table__.columns if c.foreign_keys}
    return _model_columns(model) - pk - fks - PROTECTED_FIELDS


def _parse_step(raw: dict[str, Any], scenario_name: str) -> ScenarioStep:
    entity = raw.get("entity")
    if entity not in ENTITIES:
        raise ScenarioError(
            f"{scenario_name}: unknown entity '{entity}'. Known: {', '.join(sorted(ENTITIES))}"
        )
    model = ENTITIES[entity]

    match = raw.get("match") or {}
    set_fields = raw.get("set") or {}
    if not set_fields:
        raise ScenarioError(f"{scenario_name}: step on '{entity}' sets nothing")

    unknown_match = set(match) - _model_columns(model)
    if unknown_match:
        raise ScenarioError(
            f"{scenario_name}: {entity} has no field(s) {sorted(unknown_match)} to match on"
        )

    allowed = _settable(model)
    illegal = set(set_fields) - allowed
    if illegal:
        raise ScenarioError(
            f"{scenario_name}: {entity} field(s) {sorted(illegal)} cannot be set by a "
            f"scenario. Settable: {sorted(allowed)}"
        )

    return ScenarioStep(
        entity=entity,
        match=match,
        set_fields=set_fields,
        description=raw.get("description", ""),
    )


def load_scenario(tenant_slug: str, name: str, packs_dir: Path = PACKS_DIR) -> Scenario:
    path = packs_dir / tenant_slug / f"{name}.yaml"
    if not path.exists():
        raise ScenarioNotFoundError(
            f"No scenario '{name}' for tenant '{tenant_slug}' at {path}. "
            f"Add a YAML file rather than editing code."
        )

    with path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    subscribers = raw.get("subscribers") or {}
    identifiers = subscribers.get("identifiers") or []
    if not identifiers:
        raise ScenarioError(f"{name}: names no subscribers to act on")

    return Scenario(
        name=raw.get("name", name),
        title=raw.get("title", name),
        description=raw.get("description", "").strip(),
        reset_first=bool(raw.get("reset_first", False)),
        identifiers=[str(i) for i in identifiers],
        steps=[_parse_step(s, name) for s in raw.get("steps", [])],
    )


def list_scenarios(tenant_slug: str, packs_dir: Path = PACKS_DIR) -> list[Scenario]:
    directory = packs_dir / tenant_slug
    if not directory.exists():
        return []
    scenarios = [
        load_scenario(tenant_slug, p.stem, packs_dir)
        for p in sorted(directory.glob("*.yaml"))
    ]
    return sorted(scenarios, key=lambda s: s.name)


def _target_party_ids(db: Session, tenant: Tenant, identifiers: list[str]) -> list[uuid.UUID]:
    """Resolve the scenario's subscribers inside this tenant only.

    Identifiers come from the pack, so no subscriber id is ever hardcoded in engine
    code, and an identifier belonging to another tenant simply resolves to nothing.
    """
    rows = (
        db.execute(
            select(Identity.party_id).where(
                Identity.tenant_id == tenant.tenant_id,
                Identity.value.in_(identifiers),
            )
        )
        .scalars()
        .all()
    )
    return list(dict.fromkeys(rows))


def _log(
    db: Session, tenant: Tenant, action: str, scenario: str, rows: int, summary: str
) -> None:
    db.add(
        ScenarioEvent(
            tenant_id=tenant.tenant_id,
            action=action,
            scenario=scenario,
            summary=summary[:512],
            rows_changed=rows,
        )
    )


def _baseline_parties(db: Session, tenant: Tenant, pack: dict[str, Any]) -> list[SeedParty]:
    """Rebuild the seeder's party list without re-running the spine seed.

    Party keys are uuid5 of (slug, "party", index), so the mapping is recomputable;
    display_name comes from the row, since device labels interpolate the first name.
    """
    slug = tenant.slug
    count = int(pack["seed"]["party_count"])
    wanted = {_key(slug, "party", str(i)): i for i in range(count)}

    rows = (
        db.execute(
            select(Party).where(
                Party.tenant_id == tenant.tenant_id, Party.party_id.in_(wanted)
            )
        )
        .scalars()
        .all()
    )
    return [
        SeedParty(index=wanted[p.party_id], party_id=p.party_id, display_name=p.display_name)
        for p in rows
    ]


def reset(
    db: Session,
    tenant: Tenant,
    seed_packs_dir: Path = SEED_PACKS_DIR,
    log: bool = True,
) -> ScenarioResult:
    """Restore the tenant's seeded baseline in place. Idempotent.

    Clears the tenant's interaction/CSAT/telemetry events too, so a demo restarts from a
    genuinely clean slate: last_channel derives again and the telemetry feed is empty.
    The scenario audit log (who applied/reset what) is deliberately kept.
    """
    pack = load_pack(tenant.slug, seed_packs_dir)
    network_cfg = pack["seed"].get("network")

    rows = 0
    if network_cfg:
        parties = _baseline_parties(db, tenant, pack)
        counts = seed_networks(db, tenant.tenant_id, tenant.slug, parties, network_cfg, _key)
        rows = counts.gateways + counts.access_points + counts.radios + counts.devices

    db.execute(delete(Event).where(Event.tenant_id == tenant.tenant_id))

    summary = f"Restored the seeded baseline for {tenant.slug} ({rows} entities)"
    if log:
        _log(db, tenant, "reset", "", rows, summary)
    db.commit()

    return ScenarioResult(action="reset", scenario="", rows_changed=rows, summary=summary)


def apply(
    db: Session,
    tenant: Tenant,
    name: str,
    packs_dir: Path = PACKS_DIR,
    seed_packs_dir: Path = SEED_PACKS_DIR,
) -> ScenarioResult:
    """Stage a named scenario. Idempotent when the pack sets reset_first."""
    scenario = load_scenario(tenant.slug, name, packs_dir)

    if scenario.reset_first:
        reset(db, tenant, seed_packs_dir, log=False)

    party_ids = _target_party_ids(db, tenant, scenario.identifiers)
    if not party_ids:
        raise ScenarioError(
            f"{name}: none of {scenario.identifiers} resolve to a subscriber of "
            f"tenant '{tenant.slug}'"
        )

    rows = 0
    for step in scenario.steps:
        model = ENTITIES[step.entity]
        stmt = (
            update(model)
            .where(
                # Both filters matter: tenant_id is the isolation boundary, party_id
                # keeps a scenario to the subscribers its pack names.
                model.tenant_id == tenant.tenant_id,
                model.party_id.in_(party_ids),
            )
            .values(**step.set_fields)
        )
        for field_name, value in step.match.items():
            stmt = stmt.where(getattr(model, field_name) == value)

        result = cast(CursorResult[Any], db.execute(stmt))
        rows += result.rowcount or 0

    db.flush()

    # Telemetry seam: staging a fault raises network.degraded for whoever ends up
    # faulted. Driven by the resulting verdict, so `healthy`/reset emit nothing.
    for party_id in party_ids:
        emit_network_telemetry(db, tenant, party_id, commit=False)

    summary = f"Applied '{scenario.name}' to {len(party_ids)} subscriber(s), {rows} rows set"
    _log(db, tenant, "apply", scenario.name, rows, summary)
    db.commit()

    return ScenarioResult(
        action="apply", scenario=scenario.name, rows_changed=rows, summary=summary
    )


def recent_events(db: Session, tenant: Tenant, limit: int = 20) -> list[ScenarioEvent]:
    return list(
        db.execute(
            select(ScenarioEvent)
            .where(ScenarioEvent.tenant_id == tenant.tenant_id)
            .order_by(ScenarioEvent.created_at.desc(), ScenarioEvent.event_id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
