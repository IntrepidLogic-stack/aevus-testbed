"""Scheduler-level regression tests for comms-loss / staleness detection.

Reproduces the field scenario: power was pulled on a remote JR900 radio
and SCADAPack 470 and the dashboard never alarmed. Root cause was that
``_poll_cycle`` early-returned when a collector returned no readings and
``AlertEngine.evaluate_offline`` was never invoked from anywhere.

These tests pin the fix:
  1. An empty poll triggers _handle_offline → OFFLINE alert is generated,
     persisted, and broadcast.
  2. The independent staleness sweep fires the same alert even if the
     poll task itself is wedged.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ``src.collectors.__init__`` eagerly imports every concrete collector,
# which drags in optional protocol libs (pymodbus, pysnmp, ...). The
# scheduler only needs the BaseCollector type for annotations, so stub the
# heavy deps when they're not installed in the test environment. This keeps
# the regression test runnable on a bare interpreter.
class _PermissiveModule(types.ModuleType):
    """Module stub that returns a MagicMock for any attribute access, so
    ``from stub import Anything`` works without pre-declaring symbols."""

    def __getattr__(self, name: str):  # type: ignore[override]
        return MagicMock(name=f"{self.__name__}.{name}")


for _name in (
    "pymodbus",
    "pymodbus.client",
    "pymodbus.exceptions",
    "pysnmp",
    "pysnmp.hlapi",
    "pysnmp.hlapi.asyncio",
    "influxdb_client",
    "influxdb_client.client",
    "influxdb_client.client.write_api",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)

from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.models.asset import Asset  # noqa: E402
from src.models.telemetry import RawTelemetry  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402


class _DeadCollector:
    """Duck-typed collector that always returns no readings — simulates a
    powered-off device. We avoid subclassing BaseCollector here so this test
    module doesn't pull in optional collector dependencies (pymodbus etc.)
    via ``src.collectors.__init__``."""

    def __init__(self, asset_id: str, host: str = "192.0.2.1", poll_interval: int = 5):
        self.asset_id = asset_id
        self.host = host
        self.poll_interval = poll_interval
        self.last_poll = None
        self.consecutive_failures = 0

    async def safe_poll(self):
        self.consecutive_failures += 1
        return []


class _PartialCollector:
    """Duck-typed collector that returns only a subset of its expected
    metrics — simulates a SCADAPack with one Modbus channel timing out
    while the rest still read."""

    expected_metrics = frozenset({"suction_pressure", "discharge_pressure", "battery_voltage"})

    def __init__(self, asset_id: str, poll_interval: int = 5, emit: Optional[set[str]] = None):
        self.asset_id = asset_id
        self.host = "192.0.2.2"
        self.poll_interval = poll_interval
        self.last_poll = None
        self.consecutive_failures = 0
        # By default, drop suction_pressure to simulate a stuck channel.
        self._emit = emit if emit is not None else {"discharge_pressure", "battery_voltage"}

    async def safe_poll(self):
        return [
            RawTelemetry(
                asset_id=self.asset_id,
                metric=m,
                value=100.0,
                unit="PSI",
                timestamp=datetime.now(timezone.utc),
                source="modbus",
            )
            for m in self._emit
        ]


def _fake_asset(asset_id: str, name: str, last_seen_age_s: int) -> Asset:
    return Asset(
        id=asset_id,
        type="rtu",
        status="good",
        name=name,
        location="Lab Cabinet",
        health=92,
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=last_seen_age_s),
        vendor="Schneider",
        model="SCADAPack 470",
        vitals=[],
        events=[],
    )


def _build_scheduler(asset: Asset) -> tuple[PollScheduler, MagicMock, AlertEngine]:
    db = MagicMock()
    db.get_asset.return_value = asset
    db.upsert_asset = MagicMock()
    db.save_alert = MagicMock()
    db.list_assets.return_value = [asset]

    influx = MagicMock()
    alert_engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=alert_engine)
    return sched, db, alert_engine


@pytest.mark.asyncio
async def test_poll_cycle_empty_readings_fires_offline_alert(monkeypatch):
    """Pulling power on a device → next poll returns [] → OFFLINE alert
    must be generated, persisted, and broadcast. This is the exact
    regression that let the JR900 + SCADAPack power-off go silent."""
    asset = _fake_asset("RTU-01", "SCADAPack 470", last_seen_age_s=30)
    sched, db, engine = _build_scheduler(asset)

    broadcasts: list[tuple[str, Any]] = []

    async def _capture(event_type: str, data: Any) -> None:
        broadcasts.append((event_type, data))

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _capture)

    collector = _DeadCollector("RTU-01", poll_interval=5)
    await sched._poll_cycle("RTU-01", collector)

    # Alert engine should now hold one open OFFLINE alert.
    open_alerts = engine.open_alerts
    assert len(open_alerts) == 1
    assert open_alerts[0].severity == "critical"
    assert "comms loss" in open_alerts[0].message.lower()

    # Persisted to SQLite.
    assert db.save_alert.called
    # Asset status flipped to offline and re-upserted.
    assert db.upsert_asset.called
    assert asset.status == "offline"

    # Broadcast: at least one alert_update.
    event_types = [b[0] for b in broadcasts]
    assert "alert_update" in event_types


@pytest.mark.asyncio
async def test_poll_cycle_fresh_device_no_offline_alert(monkeypatch):
    """If the device just polled successfully a moment ago, an empty
    cycle should NOT immediately fire OFFLINE — only after the
    staleness threshold is exceeded."""
    asset = _fake_asset("RTU-01", "SCADAPack 470", last_seen_age_s=2)
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...
    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    collector = _DeadCollector("RTU-01", poll_interval=5)
    await sched._poll_cycle("RTU-01", collector)

    assert engine.open_alerts == []
    assert asset.status == "good"  # untouched


@pytest.mark.asyncio
async def test_staleness_sweep_fires_independent_of_poll_loop(monkeypatch):
    """If the poll task is wedged, the independent sweep must still
    detect comms loss. This is the defense-in-depth guarantee."""
    asset = _fake_asset("RAD-01", "Trio JR900 #1", last_seen_age_s=200)
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...
    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    collector = _DeadCollector("RAD-01", poll_interval=30)
    sched.register("RAD-01", collector)

    # Drive a single sweep iteration directly rather than starting the
    # background task — keeps the test deterministic.
    await sched._handle_offline("RAD-01", collector)

    assert len(engine.open_alerts) == 1
    assert engine.open_alerts[0].asset_id == "RAD-01"
    assert asset.status == "offline"


@pytest.mark.asyncio
async def test_poll_cycle_partial_telemetry_fires_warning(monkeypatch):
    """Device responds but is missing a metric → PARTIAL_TELEMETRY warning
    must fire. This is the failure mode the comms-loss path cannot catch
    on its own (poll returned data, just not all of it)."""
    asset = _fake_asset("RTU-01", "SCADAPack 470", last_seen_age_s=0)
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...
    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)
    # Skip InfluxDB write path.
    sched.influx.write_readings = MagicMock()
    # Stub prediction / db side effects we don't care about here.
    sched.prediction_engine.get_prediction = MagicMock(return_value=None)

    collector = _PartialCollector("RTU-01", poll_interval=5)
    await sched._poll_cycle("RTU-01", collector)

    partial = [a for a in engine.open_alerts if "partial" in a.message.lower()]
    assert len(partial) == 1
    assert partial[0].severity == "warning"
    assert "suction_pressure" in partial[0].message
    assert db.save_alert.called


@pytest.mark.asyncio
async def test_partial_telemetry_resolves_when_complete(monkeypatch):
    """When the dropped channel comes back, the warning auto-resolves."""
    asset = _fake_asset("RTU-01", "SCADAPack 470", last_seen_age_s=0)
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...
    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)
    sched.influx.write_readings = MagicMock()
    sched.prediction_engine.get_prediction = MagicMock(return_value=None)

    # Cycle 1: one metric missing.
    bad = _PartialCollector("RTU-01", poll_interval=5)
    await sched._poll_cycle("RTU-01", bad)
    assert any("partial" in a.message.lower() for a in engine.open_alerts)

    # Cycle 2: device emits all expected metrics.
    good = _PartialCollector(
        "RTU-01",
        poll_interval=5,
        emit={"suction_pressure", "discharge_pressure", "battery_voltage"},
    )
    await sched._poll_cycle("RTU-01", good)
    assert not any("partial" in a.message.lower() for a in engine.open_alerts)


@pytest.mark.asyncio
async def test_offline_alert_resolves_when_device_returns(monkeypatch):
    """When the device recovers and its last_seen advances, the OFFLINE
    alert must auto-resolve."""
    asset = _fake_asset("RTU-01", "SCADAPack 470", last_seen_age_s=120)
    sched, db, engine = _build_scheduler(asset)

    async def _noop(*a, **kw): ...
    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    collector = _DeadCollector("RTU-01", poll_interval=5)
    await sched._handle_offline("RTU-01", collector)
    assert len(engine.open_alerts) == 1

    # Device comes back.
    asset.last_seen = datetime.now(timezone.utc)
    db.get_asset.return_value = asset
    await sched._handle_offline("RTU-01", collector)

    assert engine.open_alerts == []
