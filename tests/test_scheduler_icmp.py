"""End-to-end tests for the ICMP probe consumer path in PollScheduler.

ReachabilityEvent in → alert state change persisted + WebSocket broadcast.
The probe's actual ICMP socket work is exercised by the icmplib library;
here we inject ReachabilityEvent instances directly into the queue.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime, timezone
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
    "influxdb_client",
    "influxdb_client.client",
    "influxdb_client.client.write_api",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)


from src.collectors.icmp_probe import ICMPProbe, ReachabilityEvent  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
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


def _build_scheduler() -> tuple[PollScheduler, MagicMock, AlertEngine]:
    asset = _fake_asset()
    db = MagicMock()
    db.get_asset.return_value = asset
    db.save_alert = MagicMock()
    db.list_assets.return_value = [asset]

    influx = MagicMock()
    engine = AlertEngine()
    sched = PollScheduler(db=db, influx=influx, alert_engine=engine)
    return sched, db, engine


@pytest.mark.asyncio
async def test_handle_reachability_down_persists_and_broadcasts(monkeypatch):
    sched, db, engine = _build_scheduler()

    broadcasts: list[tuple[str, Any]] = []

    async def _capture(event_type: str, data: Any) -> None:
        broadcasts.append((event_type, data))

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _capture)

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

    assert len(engine.open_alerts) == 1
    assert engine.open_alerts[0].severity == "critical"
    assert db.save_alert.called
    event_types = [b[0] for b in broadcasts]
    assert "alert_update" in event_types
    assert "reachability_update" in event_types


@pytest.mark.asyncio
async def test_handle_reachability_up_resolves_down(monkeypatch):
    """Sequence: down → up. The down alert must auto-resolve."""
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    down = ReachabilityEvent(
        asset_id="RTU-01",
        host="192.168.88.21",
        state="down",
        previous_state="up",
        loss_pct=100.0,
        avg_rtt_ms=None,
        consecutive_failures=3,
    )
    up = ReachabilityEvent(
        asset_id="RTU-01",
        host="192.168.88.21",
        state="up",
        previous_state="down",
        loss_pct=0.0,
        avg_rtt_ms=2.5,
        consecutive_failures=0,
    )

    await sched._handle_reachability_event(down)
    await sched._handle_reachability_event(up)

    assert engine.open_alerts == []
    # save_alert called for both the fire and the resolve.
    assert db.save_alert.call_count >= 2


@pytest.mark.asyncio
async def test_icmp_consumer_loop_drains_queue(monkeypatch):
    """Smoke test the consumer loop wiring end to end."""
    sched, db, engine = _build_scheduler()

    async def _noop(*a, **kw): ...

    monkeypatch.setattr("src.scheduler.ws_manager.broadcast", _noop)

    probe = ICMPProbe()
    sched.register_icmp_probe(probe)

    await probe.events.put(
        ReachabilityEvent(
            asset_id="RTU-01",
            host="192.168.88.21",
            state="degraded",
            previous_state="up",
            loss_pct=25.0,
            avg_rtt_ms=45.0,
            consecutive_failures=0,
        )
    )

    sched._icmp_probe = probe
    task = asyncio.create_task(sched._icmp_consumer_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert any(a.severity == "warning" for a in engine.open_alerts)
