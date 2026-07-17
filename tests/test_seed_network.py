from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Party
from app.modules.network.models import AccessPoint, ConnectedDevice, Gateway, Radio
from app.seed.generator import load_pack, seed_tenant


def _count(db: Session, model: type) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _demo_device(db: Session) -> ConnectedDevice:
    """The demo subscriber's phone, matched by its stable pack key."""
    return db.execute(
        select(ConnectedDevice)
        .join(Party, Party.party_id == ConnectedDevice.party_id)
        .where(ConnectedDevice.seed_key == "phone", ConnectedDevice.label.like("%'s Phone"))
        .order_by(Party.display_name)
        .limit(1)
    ).scalar_one()


def test_seed_creates_the_expected_topology(db: Session) -> None:
    result = seed_tenant(db, "northwind")

    # The demo subscriber plus 3 standard homes.
    assert result.gateways == 4
    assert _count(db, Gateway) == 4
    assert _count(db, AccessPoint) == 8
    assert _count(db, Radio) == 13
    assert _count(db, ConnectedDevice) == 9


def test_the_seeded_baseline_is_healthy(db: Session) -> None:
    """The seed stages nothing. Faults come from the scenario engine, so a reset has a
    clean state to restore and the pack does not accrete every demo's staged fault."""
    seed_tenant(db, "northwind")

    phone = _demo_device(db)
    assert phone.band == "5"
    assert phone.rssi == -48
    assert phone.steer_eligible is True

    aps = db.execute(select(AccessPoint)).scalars().all()
    assert {ap.status for ap in aps} == {"online"}

    gateways = db.execute(select(Gateway)).scalars().all()
    assert {g.wan_status for g in gateways} == {"online"}


def test_seed_keys_are_populated(db: Session) -> None:
    """Scenarios match on seed_key, so every seeded entity must carry one."""
    seed_tenant(db, "northwind")

    assert _demo_device(db).seed_key == "phone"
    assert {ap.seed_key for ap in db.execute(select(AccessPoint)).scalars()} == {"hub", "ext1"}
    assert {g.seed_key for g in db.execute(select(Gateway)).scalars()} == {"gateway"}
    assert "hub-2.4" in {r.seed_key for r in db.execute(select(Radio)).scalars()}


def test_device_labels_interpolate_the_party_name(db: Session) -> None:
    seed_tenant(db, "northwind")

    phone = _demo_device(db)
    party = db.execute(select(Party).where(Party.party_id == phone.party_id)).scalar_one()

    assert phone.label == f"{party.display_name.split()[0]}'s Phone"


def test_macs_are_synthetic_and_locally_administered(db: Session) -> None:
    seed_tenant(db, "northwind")

    devices = db.execute(select(ConnectedDevice)).scalars().all()
    for device in devices:
        # 02: prefix is the locally-administered range: it cannot be a real vendor MAC.
        assert device.mac.startswith("02:")
        assert len(device.mac) == 17
    assert len({d.mac for d in devices}) == len(devices)


def test_seed_is_idempotent_for_networks(db: Session) -> None:
    seed_tenant(db, "northwind")
    first = (
        _count(db, Gateway),
        _count(db, AccessPoint),
        _count(db, Radio),
        _count(db, ConnectedDevice),
    )

    seed_tenant(db, "northwind")
    second = (
        _count(db, Gateway),
        _count(db, AccessPoint),
        _count(db, Radio),
        _count(db, ConnectedDevice),
    )

    assert first == second


def test_reseed_restores_the_baseline(db: Session) -> None:
    """A re-seed still restores the baseline. `reset` is the fast in-place path for
    between takes; this is the belt-and-braces one."""
    seed_tenant(db, "northwind")
    phone = _demo_device(db)
    device_id = phone.device_id

    # Simulate a demo run leaving the phone somewhere else.
    phone.band = "2.4"
    phone.rssi = -78
    db.add(phone)
    db.commit()

    seed_tenant(db, "northwind")

    restored = db.get(ConnectedDevice, device_id)
    assert restored is not None
    assert restored.band == "5"
    assert restored.rssi == -48


def test_network_ids_are_deterministic(db: Session) -> None:
    seed_tenant(db, "northwind")
    first = sorted(str(d.device_id) for d in db.execute(select(ConnectedDevice)).scalars())

    seed_tenant(db, "northwind")
    second = sorted(str(d.device_id) for d in db.execute(select(ConnectedDevice)).scalars())

    assert first == second


def test_editing_the_network_pack_does_not_strand_rows(db: Session, tmp_path: Path) -> None:
    """The locked seed-authority rule, applied to the network tables."""
    pack = load_pack("northwind")
    (tmp_path / "northwind").mkdir()

    def write(p: dict) -> None:
        (tmp_path / "northwind" / "pack.yaml").write_text(yaml.safe_dump(p))

    write(pack)
    seed_tenant(db, "northwind", packs_dir=tmp_path)
    assert _count(db, Gateway) == 4

    # The pack stops giving networks to the healthy subscribers.
    pack["seed"]["network"]["assign"] = {"demo_home": [0]}
    write(pack)
    seed_tenant(db, "northwind", packs_dir=tmp_path)

    assert _count(db, Gateway) == 1
    assert _count(db, AccessPoint) == 2
    assert _count(db, ConnectedDevice) == 3


def test_dropping_the_network_section_removes_every_topology(
    db: Session, tmp_path: Path
) -> None:
    pack = load_pack("northwind")
    (tmp_path / "northwind").mkdir()

    def write(p: dict) -> None:
        (tmp_path / "northwind" / "pack.yaml").write_text(yaml.safe_dump(p))

    write(pack)
    seed_tenant(db, "northwind", packs_dir=tmp_path)
    assert _count(db, Gateway) == 4

    del pack["seed"]["network"]
    write(pack)
    seed_tenant(db, "northwind", packs_dir=tmp_path)

    assert _count(db, Gateway) == 0
    assert _count(db, AccessPoint) == 0
    assert _count(db, Radio) == 0
    assert _count(db, ConnectedDevice) == 0
    # The spine survives; only the networks went.
    assert _count(db, Party) == 10


def test_seeding_one_tenant_leaves_another_tenants_network_alone(
    db: Session, seeded_acme: None
) -> None:
    acme_gateways = _count(db, Gateway)
    assert acme_gateways == 1

    seed_tenant(db, "northwind")

    # northwind's 4 added, acme's 1 untouched.
    assert _count(db, Gateway) == acme_gateways + 4
