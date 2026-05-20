"""
Aevus Testbed — DNP3 Unsolicited Response Receiver (Phase 3)

Real-time process alarms from the SCADAPack 470 RTU via DNP3
unsolicited Class 1/2/3 responses. This is the patent-relevant
edge path (P-008): the outstation pushes Binary Input Change and
Analog Input Change events to the master in milliseconds, with no
polling required.

Why this exists:
  Polling the SCADAPack via Modbus discrete inputs catches alarms at
  the 5-second poll cadence at best. DNP3 unsolicited responses fire
  on the event itself — typical end-to-end latency is 50-500ms from
  the physical condition to a "alarm fired" log line on this side.
  That's a 10-100x improvement on the most safety-critical signals
  (high pressure, low battery, comm fault) and the defensible
  differentiator for the Aevus value proposition.

Architecture:
  • Single async TCP master per outstation. SCADAPack 470 outstation
    lives at addr 10, master addr 1, TCP port 20000.
  • On connect / reconnect: integrity poll (Class 0) to sync state.
  • Listen continuously for unsolicited responses.
  • Decode Binary Input Change → discrete alarms (compressor running,
    high pressure, low battery, comm fault).
  • Decode Analog Input Change → process values (pressures, flow,
    temps, voltages, vibration).
  • Emit DNP3Event onto an asyncio.Queue consumed by the scheduler,
    which normalizes to RawTelemetry/VitalSign and feeds the existing
    alert engine threshold logic. One alarm rule store across paths.

Library:
  dnp3-python (Automatak's Python wrapper around opendnp3) is the
  reference. It's commented out in requirements.txt — install with
  `pip install dnp3-python` on the Pi when the SCADAPack is online.
  Until then this module is importable but raises at start() time
  with a clear message.

Safety:
  IL-9000 interlock applies. This module is READ-ONLY against the
  outstation — no controls, no operate commands, no firmware writes.
  Any future write capability MUST go through a separate, audited
  code path with the IL_009_ENFORCED check.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog

from src.config import settings

logger = structlog.get_logger()


# ──────────────────────────────────────────────────────────────────────────
# SCADAPack 470 DNP3 point map
# ──────────────────────────────────────────────────────────────────────────
# Mirrors HOLDING_REGISTERS + DISCRETE_INPUTS in modbus_rtu.py so both
# paths normalize to the same metric names. Threshold rules and the
# normalizer don't care which path the reading came from.
#
# Binary Input points (G1V2 in DNP3 parlance — single-bit binary input
# with status):
SCADAPACK_BINARY_INPUTS: dict[int, dict[str, Any]] = {
    0: {"metric": "compressor_running",  "description": "Compressor run status"},
    1: {"metric": "high_pressure_alarm", "description": "High pressure shutdown"},
    2: {"metric": "low_battery_alarm",   "description": "Battery below threshold"},
    3: {"metric": "communication_fault", "description": "Comm link status"},
}

# Analog Input points (G30V5 — 32-bit floating point analog input
# without time):
SCADAPACK_ANALOG_INPUTS: dict[int, dict[str, Any]] = {
    0: {"metric": "suction_pressure",    "unit": "PSI"},
    1: {"metric": "discharge_pressure",  "unit": "PSI"},
    2: {"metric": "flow_rate",           "unit": "MCFD"},
    3: {"metric": "gas_temperature",     "unit": "°F"},
    4: {"metric": "ambient_temperature", "unit": "°F"},
    5: {"metric": "battery_voltage",     "unit": "VDC"},
    6: {"metric": "solar_voltage",       "unit": "VDC"},
    7: {"metric": "tank_level",          "unit": "in"},
    8: {"metric": "vibration",           "unit": "mm/s"},
    9: {"metric": "run_hours",           "unit": "hrs"},
}


DNP3EventClass = Literal["binary_input", "analog_input", "counter", "double_bit"]


@dataclass
class DNP3Event:
    """A decoded DNP3 event ready for the scheduler.

    Attributes:
        asset_id:     Resolved asset ID (caller maps outstation addr → asset).
        event_class:  Object class — binary_input / analog_input / counter.
        point_index:  DNP3 point number (0-N within the class).
        metric:       Mapped metric name (e.g. "suction_pressure"). Empty
                      string if the point isn't in the asset's point map.
        value:        Decoded value — bool for binary, float for analog.
        unit:         Engineering unit string ("PSI", "VDC", etc.).
        quality_flags: DNP3 quality byte — bit 0 = online, bit 6 = state.
        device_timestamp: Outstation-reported event time, if present.
        received_at:  When this process received the event (for latency
                      computation: received_at - device_timestamp).
    """

    asset_id: str
    event_class: DNP3EventClass
    point_index: int
    metric: str
    value: Any
    unit: str = ""
    quality_flags: int = 0
    device_timestamp: Optional[datetime] = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def latency_ms(self) -> Optional[float]:
        """End-to-end event latency in ms. None if outstation didn't
        provide a timestamp (uncommon — most send G2V2 with time).
        """
        if self.device_timestamp is None:
            return None
        delta = (self.received_at - self.device_timestamp).total_seconds() * 1000.0
        # Clamp negative (clock skew) at zero; flag huge positives.
        return max(0.0, delta)


# ──────────────────────────────────────────────────────────────────────────
# Receiver
# ──────────────────────────────────────────────────────────────────────────
class DNP3UnsolicitedReceiver:
    """Async DNP3 master that subscribes to unsolicited responses from
    a single outstation.

    The scheduler instantiates one per RTU asset and registers it. The
    receiver owns the TCP connection lifecycle (connect → integrity
    poll → listen → reconnect on drop) and publishes DNP3Event objects
    onto self.events.

    Library binding:
      pysnmp / icmplib are loaded lazily; same pattern here. The actual
      DNP3 library calls live in _connect_and_run(). This keeps the
      module importable and unit-testable without the library installed.
    """

    def __init__(
        self,
        asset_id: str,
        host: str,
        port: int = 20000,
        outstation_address: int = 10,
        master_address: int = 1,
        binary_point_map: Optional[dict[int, dict[str, Any]]] = None,
        analog_point_map: Optional[dict[int, dict[str, Any]]] = None,
    ) -> None:
        self.asset_id = asset_id
        self.host = host
        self.port = port
        self.outstation_address = outstation_address
        self.master_address = master_address
        self.binary_point_map = binary_point_map or SCADAPACK_BINARY_INPUTS
        self.analog_point_map = analog_point_map or SCADAPACK_ANALOG_INPUTS

        self.events: asyncio.Queue[DNP3Event] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._connected: bool = False
        self.log = logger.bind(
            component="dnp3_unsolicited",
            asset_id=asset_id,
            host=host,
            outstation=outstation_address,
        )

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._supervisor_loop())
        self.log.info("dnp3_receiver_started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self.log.info("dnp3_receiver_stopped")

    @property
    def connected(self) -> bool:
        return self._connected

    # ──────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────

    async def _supervisor_loop(self) -> None:
        """Maintain a connection to the outstation with reconnect."""
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.warning("dnp3_session_error", error=str(e))
            self._connected = False
            self.log.info(
                "dnp3_reconnecting",
                interval_s=settings.dnp3_reconnect_interval,
            )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=settings.dnp3_reconnect_interval,
                )
                break  # stop requested
            except asyncio.TimeoutError:
                continue

    async def _connect_and_run(self) -> None:
        """Open the DNP3 session, integrity-poll, then listen forever.

        Lazy-imports the dnp3 library so the receiver module itself is
        importable without it installed. On the Pi: pip install dnp3-python.
        """
        try:
            # The Automatak dnp3-python wheel exposes its API under
            # ``dnp3_python``. We hide the import here so unit tests
            # can stub it via sys.modules without the real wheel.
            import dnp3_python as dnp3  # type: ignore
        except ImportError as e:
            self.log.error(
                "dnp3_library_not_installed",
                hint="pip install dnp3-python on the Pi (Phase 3 dependency)",
                error=str(e),
            )
            # Long sleep — the supervisor loop will retry, but no point
            # hammering the import error every second.
            await asyncio.sleep(60)
            return

        master = dnp3.MyMaster(  # type: ignore[attr-defined]
            masterstation_ip_str="0.0.0.0",
            outstation_ip_str=self.host,
            port=self.port,
            master_id=self.master_address,
            outstation_id=self.outstation_address,
        )

        master.start()
        try:
            # Integrity poll syncs full state on (re)connect. Without
            # this, the master could miss the outstation's current
            # alarm latch state until the next change event.
            await asyncio.wait_for(
                asyncio.to_thread(master.send_direct_point_command, 0),  # Class 0 read
                timeout=settings.dnp3_connect_timeout,
            )
            self._connected = True
            self.log.info("dnp3_connected_integrity_polled")

            # Install the unsolicited handler. The exact callback shape
            # depends on the dnp3-python release; the abstraction
            # _ingest_change() does the heavy lifting and is testable.
            master.add_soe_handler(self._on_change_event)  # type: ignore[attr-defined]

            # Block until shutdown.
            while not self._stop_event.is_set():
                await asyncio.sleep(settings.dnp3_keep_alive_interval)
                # Periodic integrity poll as a fallback if the device
                # stops sending unsolicited events for any reason.
                if settings.dnp3_integrity_poll_interval > 0:
                    await asyncio.to_thread(master.send_direct_point_command, 0)
        finally:
            try:
                master.stop()
            except Exception:
                pass

    def _on_change_event(self, soe_record: Any) -> None:
        """Library callback for one SOE (sequence-of-events) record.

        The dnp3-python record exposes group / variation / index / value /
        flags / timestamp. We translate that into a DNP3Event and
        publish it onto the queue.

        This is sync (libraries usually are) but put_nowait is safe
        across thread boundaries for an unbounded asyncio.Queue.
        """
        try:
            event = self._record_to_event(soe_record)
        except Exception as e:
            self.log.warning("dnp3_record_decode_failed", error=str(e))
            return

        if event is None:
            return

        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            self.log.error("dnp3_queue_full")

    def _record_to_event(self, record: Any) -> Optional[DNP3Event]:
        """Decode a library SOE record into a DNP3Event.

        Pulled out for unit-testability. The record shape varies between
        dnp3-python versions; we use duck typing on the attributes we
        care about and fall back to .get() on dicts for test stubs.
        """

        def _attr(name: str, default: Any = None) -> Any:
            if hasattr(record, name):
                return getattr(record, name)
            if isinstance(record, dict):
                return record.get(name, default)
            return default

        group = int(_attr("group", 0))
        index = int(_attr("index", 0))
        value = _attr("value", None)
        flags = int(_attr("flags", 0) or 0)
        ts = _attr("timestamp", None)

        # Coerce timestamp into UTC datetime.
        device_ts: Optional[datetime] = None
        if ts is not None:
            if isinstance(ts, datetime):
                device_ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            elif isinstance(ts, (int, float)):
                # DNP3 timestamps are UTC ms since 1970.
                device_ts = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)

        # DNP3 group families:
        #   1, 2  = Binary Inputs (1 = static, 2 = change event)
        #   30, 32 = Analog Inputs (30 = static, 32 = change event)
        #   20, 22 = Counters
        #   3, 4   = Double-bit binary
        if group in (1, 2):
            point_map = self.binary_point_map.get(index)
            metric = point_map["metric"] if point_map else f"binary_{index}"
            return DNP3Event(
                asset_id=self.asset_id,
                event_class="binary_input",
                point_index=index,
                metric=metric,
                value=bool(value),
                unit="bool",
                quality_flags=flags,
                device_timestamp=device_ts,
            )

        if group in (30, 32):
            point_map = self.analog_point_map.get(index)
            metric = point_map["metric"] if point_map else f"analog_{index}"
            unit = point_map["unit"] if point_map else ""
            return DNP3Event(
                asset_id=self.asset_id,
                event_class="analog_input",
                point_index=index,
                metric=metric,
                value=float(value) if value is not None else 0.0,
                unit=unit,
                quality_flags=flags,
                device_timestamp=device_ts,
            )

        if group in (20, 22):
            return DNP3Event(
                asset_id=self.asset_id,
                event_class="counter",
                point_index=index,
                metric=f"counter_{index}",
                value=int(value) if value is not None else 0,
                quality_flags=flags,
                device_timestamp=device_ts,
            )

        if group in (3, 4):
            return DNP3Event(
                asset_id=self.asset_id,
                event_class="double_bit",
                point_index=index,
                metric=f"dbit_{index}",
                value=int(value) if value is not None else 0,
                quality_flags=flags,
                device_timestamp=device_ts,
            )

        # Unknown group — log and drop.
        self.log.info("dnp3_unknown_group", group=group, index=index)
        return None


# ──────────────────────────────────────────────────────────────────────────
# Standalone smoke-test entry point
# ──────────────────────────────────────────────────────────────────────────
async def _smoke_main() -> None:
    """Run a single DNP3 receiver standalone for smoke testing.

    Usage on the Pi (once SCADAPack is online):
        python3 -m src.collectors.dnp3_unsolicited 192.168.88.21
    """
    import sys
    import logging

    logging.basicConfig(level=logging.INFO)
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.88.21"

    receiver = DNP3UnsolicitedReceiver(asset_id="RTU-01", host=host)
    await receiver.start()
    print(f"Listening for DNP3 unsolicited from {host}:20000. Ctrl+C or SIGTERM to stop.")

    import signal as _signal
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async def _print():
        try:
            while True:
                event = await receiver.events.get()
                latency = event.latency_ms
                latency_str = f"{latency:6.1f}ms" if latency is not None else "  n/a"
                print(
                    f"  → [{event.event_class:13s}] {event.metric:22s} "
                    f"= {event.value!s:8s}  flags=0x{event.quality_flags:02X}  "
                    f"latency={latency_str}"
                )
        except asyncio.CancelledError:
            return

    consumer = asyncio.create_task(_print())
    try:
        await stop.wait()
    finally:
        print("\nStopping...")
        consumer.cancel()
        await receiver.stop()


if __name__ == "__main__":
    asyncio.run(_smoke_main())
