"""End-to-end tests for the SNMP trap consumer path in PollScheduler.

Pins the contract: TrapEvent in → alert state change persisted to SQLite
and broadcast over WebSocket. The receiver itself (UDP 162 binding,
pysnmp decoding) is tested separately — here we inject TrapEvent
instances directly into the receiver's queue and verify the consumer
loop processes them correctly.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


# Stub optional protocol libs (same pattern as test_scheduler_offline).
class _PermissiveModule(types.ModuleType):
    def __getattr__(self, name: str):
        return MagicMock(name=f"{self.__name__}.{name}")


for _name in (
    "pymodbus",
    "pymodbus.client",
    "pymodbus.exceptions",
    "pysnmp",
    "pysnmp.hlapi",
    "pysnmp.hlapi.asyncio",
    "pysnmp.entity",
    "pysnmp.entity.rfc3413",
    "pysnmp.carrier",
    "pysnmp.carrier.asyncio",
    "pysnmp.carrier.asyncio.dgram",
    "influxdb_client",
    "influxdb_client.client",
    "influxdb_client.client.write_api",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)


from src.collectors.snmp_trap_receiver import SNMPTrapReceiver, TrapEvent  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.models.asset import Asset  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402


def _fake_asset(asset_id: str, name: str, ip: str = "192.168.88.11") -> Asset:
    return Asset(
        id=asset_id,
        type="radio",
        status="good",
        name=name,
        location="Lab Cabinet",
        health=92,
        last_seen=datetime.now(UTC),
        vendor="Trio",
        model="JR900",
        ip_address=ip,
        vitals=[],
        events=[],
    )


def _build_scheduler(asset: Asset) -> tuple[PollScheduler, MagicMock, AlertEngine]:
    db = MagicMock()
    db.get_asset.return_value = asset
    db.get_asset_by_ip.return_value = asset
    db.save_alert = MagicMock()
    db.upsert_asset = MagicMock()
    db.list_assets.return_value = [asset]

    influx = MagicMock()
    engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=engine)
    return sched, db, engine


@pytest.mark.asyncio
async def test_handle_trap_event_persists_and_broadcasts(monkeypatch):
    """linkDown TrapEvent → critical alert saved to SQLite and broadcast."""
    asset = _fake_asset("SW-01", "Cisco Catalyst 2960", ip="192.168.88.2")
    sched, db, engine = _build_scheduler(asset)

    broadcasts: list[tuple[str, Any]] = []

    async def _capture(event_type: str, data: Any) -> None:
        broadcasts.append((event_type, data))

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _capture)

    event = TrapEvent(
        event_type="linkDown",
        trap_oid="1.3.6.1.6.3.1.1.5.3",
        source_ip="192.168.88.2",
        asset_id="SW-01",
        community="aevus_trap",
        varbinds={"1.3.6.1.2.1.2.2.1.1.3": 3},
    )

    await sched._handle_trap_event(event)

    assert len(engine.open_alerts) == 1
    assert engine.open_alerts[0].severity == "critical"
    assert "ifIndex 3" in engine.open_alerts[0].message
    assert db.save_alert.called
    assert any(b[0] == "alert_update" for b in broadcasts)


@pytest.mark.asyncio
async def test_handle_trap_unknown_source_dropped(monkeypatch):
    """A trap from an IP not in the asset registry must be dropped — no
    alert, no broadcast, no save. Logs a warning but does not crash."""
    sched, db, engine = _build_scheduler(_fake_asset("SW-01", "Catalyst"))
    db.get_asset_by_ip.return_value = None  # IP unknown

    broadcasts: list[tuple[str, Any]] = []

    async def _capture(event_type: str, data: Any) -> None:
        broadcasts.append((event_type, data))

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _capture)

    event = TrapEvent(
        event_type="coldStart",
        trap_oid="1.3.6.1.6.3.1.1.5.1",
        source_ip="10.99.99.99",
        asset_id=None,
        community="aevus_trap",
        varbinds={},
    )

    await sched._handle_trap_event(event)

    assert engine.open_alerts == []
    assert not db.save_alert.called
    assert broadcasts == []


@pytest.mark.asyncio
async def test_handle_trap_late_binds_asset_from_ip(monkeypatch):
    """When the receiver hasn't resolved asset_id (e.g. seeded before
    asset registry was populated), the scheduler must look it up from
    source_ip."""
    asset = _fake_asset("RAD-01", "Trio JR900 #1", ip="192.168.88.11")
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    event = TrapEvent(
        event_type="coldStart",
        trap_oid="1.3.6.1.6.3.1.1.5.1",
        source_ip="192.168.88.11",
        asset_id=None,  # not yet resolved by the receiver
        community="aevus_trap",
        varbinds={},
    )

    await sched._handle_trap_event(event)

    db.get_asset_by_ip.assert_called_with("192.168.88.11")
    assert len(engine.open_alerts) == 1
    assert engine.open_alerts[0].asset_id == "RAD-01"


@pytest.mark.asyncio
async def test_trap_consumer_loop_drains_queue(monkeypatch):
    """The consumer loop, when started, must drain queued TrapEvents
    end-to-end. This is the smoke test for the scheduler-side wiring."""
    asset = _fake_asset("SW-01", "Catalyst", ip="192.168.88.2")
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    # Register a receiver with a pre-populated queue. We never call
    # receiver.start() (which would bind UDP 162) — just use its queue
    # as a TrapEvent inbox.
    receiver = SNMPTrapReceiver()
    sched.register_trap_receiver(receiver)

    await receiver.events.put(
        TrapEvent(
            event_type="linkDown",
            trap_oid="1.3.6.1.6.3.1.1.5.3",
            source_ip="192.168.88.2",
            asset_id="SW-01",
            community="aevus_trap",
            varbinds={},
        )
    )
    await receiver.events.put(
        TrapEvent(
            event_type="linkUp",
            trap_oid="1.3.6.1.6.3.1.1.5.4",
            source_ip="192.168.88.2",
            asset_id="SW-01",
            community="aevus_trap",
            varbinds={},
        )
    )

    # Start the consumer task directly (avoids receiver.start()'s UDP bind).
    sched._trap_receiver = receiver
    task = asyncio.create_task(sched._trap_consumer_loop())
    # Let the loop process both events.
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # linkDown fired then linkUp resolved → no open link alerts.
    assert not any("link" in a.message.lower() for a in engine.open_alerts)
    # Save was called for both state changes (fire + resolve).
    assert db.save_alert.call_count >= 2
