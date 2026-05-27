"""End-to-end tests for the DNP3 unsolicited path through PollScheduler.

DNP3Event in → normalized to RawTelemetry → VitalSign → existing
alert engine threshold rules → alert persisted + broadcast. The same
threshold-rule store that handles Modbus polling fires here too, in
milliseconds instead of poll intervals.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


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
    "icmplib",
    "dnp3_python",
    "influxdb_client",
    "influxdb_client.client",
    "influxdb_client.client.write_api",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)


from src.collectors.dnp3_unsolicited import DNP3Event, DNP3UnsolicitedReceiver  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.models.asset import Asset  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402


def _fake_rtu(ip: str = "192.168.88.21") -> Asset:
    return Asset(
        id="RTU-01",
        type="rtu",
        status="good",
        name="SCADAPack 470",
        location="Lab",
        health=92,
        last_seen=datetime.now(UTC),
        vendor="Schneider",
        model="SCADAPack 470",
        ip_address=ip,
        vitals=[],
        events=[],
    )


def _build_scheduler() -> tuple[PollScheduler, MagicMock, AlertEngine]:
    asset = _fake_rtu()
    db = MagicMock()
    db.get_asset.return_value = asset
    db.save_alert = MagicMock()
    db.upsert_asset = MagicMock()
    db.list_assets.return_value = [asset]

    influx = MagicMock()
    influx.write_readings = MagicMock()
    engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=engine)
    return sched, db, engine


@pytest.mark.asyncio
async def test_high_pressure_alarm_fires_critical(monkeypatch):
    """High pressure latched at the SCADAPack → DNP3 unsolicited →
    critical alert. This is the patent-relevant demo: the alarm fires
    before any polling cycle would have caught it."""
    sched, db, engine = _build_scheduler()

    broadcasts: list[tuple[str, Any]] = []

    async def _capture(event_type: str, data: Any) -> None:
        broadcasts.append((event_type, data))

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _capture)

    event = DNP3Event(
        asset_id="RTU-01",
        event_class="binary_input",
        point_index=1,
        metric="high_pressure_alarm",
        value=True,
        unit="bool",
        quality_flags=0x81,
        device_timestamp=datetime.now(UTC),
    )

    await sched._handle_dnp3_event(event)

    critical = [a for a in engine.open_alerts if a.severity == "critical"]
    assert len(critical) == 1
    assert "high pressure" in critical[0].message.lower()
    assert db.save_alert.called
    # Latency-tracking broadcast on dnp3_event topic.
    event_types = [b[0] for b in broadcasts]
    assert "dnp3_event" in event_types


@pytest.mark.asyncio
async def test_analog_suction_pressure_threshold(monkeypatch):
    """Suction pressure crossing the critical threshold via DNP3 must
    produce the same alarm a polled reading would have, only faster."""
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    # threshold_suction_crit defaults to 900 PSI per config.py.
    event = DNP3Event(
        asset_id="RTU-01",
        event_class="analog_input",
        point_index=0,
        metric="suction_pressure",
        value=945.0,
        unit="PSI",
        quality_flags=0x01,
        device_timestamp=datetime.now(UTC),
    )

    await sched._handle_dnp3_event(event)

    assert any(
        a.severity == "critical" and "suction" in a.message.lower() for a in engine.open_alerts
    )


@pytest.mark.asyncio
async def test_dnp3_event_writes_to_influx(monkeypatch):
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    event = DNP3Event(
        asset_id="RTU-01",
        event_class="analog_input",
        point_index=5,
        metric="battery_voltage",
        value=13.2,
        unit="VDC",
        quality_flags=0x01,
        device_timestamp=datetime.now(UTC),
    )

    await sched._handle_dnp3_event(event)

    sched.influx.write_readings.assert_called()
    reading = sched.influx.write_readings.call_args[0][0][0]
    assert reading.source == "dnp3"
    assert reading.metric == "battery_voltage"
    assert reading.value == pytest.approx(13.2)


@pytest.mark.asyncio
async def test_dnp3_event_resolves_offline(monkeypatch):
    """A DNP3 unsolicited event is rock-solid proof of life — any
    open OFFLINE comms-loss or UNREACHABLE alert must auto-resolve."""
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    # Seed an OFFLINE alert by aging out the staleness threshold.
    old = datetime.now(UTC) - timedelta(seconds=200)
    engine.evaluate_offline("RTU-01", "SCADAPack 470", old, poll_interval=5)
    assert any("comms loss" in a.message.lower() for a in engine.open_alerts)

    event = DNP3Event(
        asset_id="RTU-01",
        event_class="binary_input",
        point_index=0,
        metric="compressor_running",
        value=True,
        unit="bool",
        quality_flags=0x01,
        device_timestamp=datetime.now(UTC),
    )
    await sched._handle_dnp3_event(event)

    # OFFLINE alert auto-resolved.
    assert not any("comms loss" in a.message.lower() for a in engine.open_alerts)


@pytest.mark.asyncio
async def test_dnp3_consumer_loop_drains_queue(monkeypatch):
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    receiver = DNP3UnsolicitedReceiver(asset_id="RTU-01", host="192.168.88.21")
    sched.register_dnp3_receiver(receiver)

    # Push two events into the queue directly (no library, no socket).
    await receiver.events.put(
        DNP3Event(
            asset_id="RTU-01",
            event_class="binary_input",
            point_index=2,
            metric="low_battery_alarm",
            value=True,
            unit="bool",
            quality_flags=0x81,
            device_timestamp=datetime.now(UTC),
        )
    )
    await receiver.events.put(
        DNP3Event(
            asset_id="RTU-01",
            event_class="analog_input",
            point_index=5,
            metric="battery_voltage",
            value=11.0,  # below 11.5 V critical threshold
            unit="VDC",
            quality_flags=0x01,
            device_timestamp=datetime.now(UTC),
        )
    )

    task = asyncio.create_task(sched._dnp3_consumer_loop("RTU-01"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Two critical alerts fired (low battery discrete + battery analog).
    assert sum(1 for a in engine.open_alerts if a.severity == "critical") >= 2
