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
    """The steer-eligible phone on the degraded subscriber."""
    return db.execute(
        select(ConnectedDevice).where(
            ConnectedDevice.steer_eligible.is_(True), ConnectedDevice.band == "2.4"
        )
    ).scalar_one()


def test_seed_creates_the_expected_topology(db: Session) -> None:
    result = seed_tenant(db, "northwind")

    # 1 degraded + 3 healthy subscribers get a home network.
    assert result.gateways == 4
    assert _count(db, Gateway) == 4
    assert _count(db, AccessPoint) == 8
    assert _count(db, Radio) == 13
    assert _count(db, ConnectedDevice) == 9


def test_degraded_subscriber_matches_the_pack(db: Session) -> None:
    seed_tenant(db, "northwind")

    phone = _demo_device(db)
    assert phone.band == "2.4"
    assert phone.rssi == -78
    assert phone.steer_eligible is True

    extender = db.execute(
        select(AccessPoint).where(AccessPoint.kind == "extender", AccessPoint.status == "flapping")
    ).scalar_one()
    assert extender.backhaul_quality == 34

    # WAN is healthy: the fault is inside the home, which is the demo's whole point.
    gateways = db.execute(select(Gateway)).scalars().all()
    assert {g.wan_status for g in gateways} == {"online"}


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


def test_reseed_restores_the_degraded_baseline(db: Session) -> None:
    """BE-2 has no scenario engine yet (that is BE-3), so `make seed` is what resets
    a demo. It must put the staged fault back after actions have healed it."""
    seed_tenant(db, "northwind")
    phone = _demo_device(db)
    device_id = phone.device_id

    # Simulate a demo run: the phone gets steered onto 5GHz.
    phone.band = "5"
    phone.rssi = -56
    db.add(phone)
    db.commit()

    seed_tenant(db, "northwind")

    restored = db.get(ConnectedDevice, device_id)
    assert restored is not None
    assert restored.band == "2.4"
    assert restored.rssi == -78


def test_reseed_restores_a_healed_extender(db: Session) -> None:
    seed_tenant(db, "northwind")
    extender = db.execute(
        select(AccessPoint).where(AccessPoint.kind == "extender", AccessPoint.status == "flapping")
    ).scalar_one()
    ap_id = extender.ap_id

    extender.status = "online"
    extender.backhaul_quality = 92
    db.add(extender)
    db.commit()

    seed_tenant(db, "northwind")

    restored = db.get(AccessPoint, ap_id)
    assert restored is not None
    assert restored.status == "flapping"
    assert restored.backhaul_quality == 34


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
    pack["seed"]["network"]["assign"] = {"degraded": [0]}
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
