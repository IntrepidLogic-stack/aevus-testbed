"""Scheduler-level test that events fan out to both WebSocket AND MQTT.

The MQTT publisher is replaced with an AsyncMock that captures calls.
We're not testing the aiomqtt library (it has its own tests); we're
pinning the contract that every WebSocket broadcast has a matching
MQTT publish call, and that an MQTT failure doesn't break alarming.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
    "aiomqtt",
    "influxdb_client",
    "influxdb_client.client",
    "influxdb_client.client.write_api",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)


from src.collectors.dnp3_unsolicited import DNP3Event  # noqa: E402
from src.collectors.icmp_probe import ReachabilityEvent  # noqa: E402
from src.collectors.snmp_trap_receiver import TrapEvent  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.integrations.mqtt_publisher import MQTTPublisher  # noqa: E402
from src.models.asset import Asset  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402


def _fake_asset(asset_id: str = "RTU-01", host: str = "192.168.88.21") -> Asset:
    return Asset(
        id=asset_id,
        type="rtu",
        status="good",
        name="SCADAPack 470",
        location="Lab",
        health=92,
        last_seen=datetime.now(UTC),
        vendor="Schneider",
        model="SCADAPack 470",
        ip_address=host,
        vitals=[],
        events=[],
    )


def _build(mqtt: MQTTPublisher) -> tuple[PollScheduler, MagicMock, AlertEngine]:
    asset = _fake_asset()
    db = MagicMock()
    db.get_asset.return_value = asset
    db.get_asset_by_ip.return_value = asset
    db.save_alert = MagicMock()
    db.list_assets.return_value = [asset]

    influx = MagicMock()
    influx.write_readings = MagicMock()
    engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=engine)
    sched.register_mqtt_publisher(mqtt)
    return sched, db, engine


def _stub_publisher() -> MQTTPublisher:
    """Build a publisher with every async publish method replaced by
    an AsyncMock for call inspection."""
    pub = MQTTPublisher.__new__(MQTTPublisher)  # bypass __init__
    pub.site_id = "lab"
    pub._connected = True
    pub.publish_telemetry = AsyncMock()
    pub.publish_state = AsyncMock()
    pub.publish_event = AsyncMock()
    pub.publish_alert = AsyncMock()
    pub.publish_heartbeat = AsyncMock()
    return pub


@pytest.mark.asyncio
async def test_dnp3_event_fans_out_to_mqtt(monkeypatch):
    mqtt = _stub_publisher()
    sched, db, engine = _build(mqtt)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

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

    # The critical alert must have published.
    mqtt.publish_alert.assert_called()
    # The raw DNP3 event must have published on events/dnp3.
    mqtt.publish_event.assert_called()
    # The value must have published as telemetry too (for SiteWise).
    mqtt.publish_telemetry.assert_called()


@pytest.mark.asyncio
async def test_trap_event_publishes_to_mqtt(monkeypatch):
    mqtt = _stub_publisher()
    sched, db, engine = _build(mqtt)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    trap = TrapEvent(
        event_type="linkDown",
        trap_oid="1.3.6.1.6.3.1.1.5.3",
        source_ip="192.168.88.21",
        asset_id="RTU-01",
        community="aevus_trap",
        varbinds={"1.3.6.1.2.1.2.2.1.1.3": 3},
    )

    await sched._handle_trap_event(trap)

    mqtt.publish_alert.assert_called()
    mqtt.publish_event.assert_called()
    # Inspect the topic-class kwarg: must be 'snmp-trap'.
    args, kwargs = mqtt.publish_event.call_args
    assert kwargs.get("event_class") == "snmp-trap"


@pytest.mark.asyncio
async def test_reachability_state_publishes_to_mqtt(monkeypatch):
    mqtt = _stub_publisher()
    sched, db, engine = _build(mqtt)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    event = ReachabilityEvent(
        asset_id="RTU-01",
        host="192.168.88.21",
        state="down",
        previous_state="up",
        loss_pct=100.0,
        avg_rtt_ms=None,
        consecutive_failures=3,
    )

    await sched._handle_reachability_event(event)

    mqtt.publish_alert.assert_called()
    mqtt.publish_state.assert_called()
    args, kwargs = mqtt.publish_state.call_args
    assert kwargs.get("key") == "reachability"
    assert kwargs.get("state_value") == "down"


@pytest.mark.asyncio
async def test_mqtt_publish_failure_does_not_break_alarming(monkeypatch):
    """Edge-first principle: a broken cloud must NEVER interrupt
    local alarming. If the publisher raises, the alert engine and
    SQLite writes still happen."""
    mqtt = _stub_publisher()
    mqtt.publish_alert = AsyncMock(side_effect=ConnectionError("broker dead"))
    mqtt.publish_event = AsyncMock(side_effect=ConnectionError("broker dead"))

    sched, db, engine = _build(mqtt)

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

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

    # Should NOT raise even though MQTT calls raise.
    await sched._handle_dnp3_event(event)

    # Local alarming still happened.
    assert len(engine.open_alerts) >= 1
    assert db.save_alert.called


@pytest.mark.asyncio
async def test_no_mqtt_publisher_registered_is_a_noop(monkeypatch):
    """If no publisher is registered, the scheduler must not crash —
    backward-compat with existing systemd-only deployments."""
    asset = _fake_asset()
    db = MagicMock()
    db.get_asset.return_value = asset
    db.save_alert = MagicMock()
    db.list_assets.return_value = [asset]
    influx = MagicMock()
    influx.write_readings = MagicMock()
    engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=engine)
    # Note: no register_mqtt_publisher() call.

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

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
    assert len(engine.open_alerts) >= 1
