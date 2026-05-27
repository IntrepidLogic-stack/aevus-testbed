"""Unit tests for the DNP3 unsolicited receiver — point map + decode.

We don't exercise the actual dnp3-python library here (it requires the
wheel + a live outstation); we test _record_to_event() which is the
library-agnostic decoder. The scheduler integration test in
test_scheduler_dnp3.py covers end-to-end through the alert engine.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timezone
from unittest.mock import MagicMock

import pytest


# Stub eager-imported optional libs (src.collectors.__init__ pulls in
# every concrete collector at import time; we only need the DNP3 one).
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
):
    if _name not in sys.modules:
        sys.modules[_name] = _PermissiveModule(_name)


from src.collectors.dnp3_unsolicited import (  # noqa: E402
    SCADAPACK_ANALOG_INPUTS,
    SCADAPACK_BINARY_INPUTS,
    DNP3Event,
    DNP3UnsolicitedReceiver,
)


@pytest.fixture
def receiver() -> DNP3UnsolicitedReceiver:
    return DNP3UnsolicitedReceiver(asset_id="RTU-01", host="192.168.88.21")


class TestBinaryInputDecode:
    def test_decode_high_pressure_alarm_active(self, receiver):
        # G2 (Binary Input Change), index 1 = high_pressure_alarm
        record = {"group": 2, "index": 1, "value": True, "flags": 0x81}
        event = receiver._record_to_event(record)
        assert event is not None
        assert event.event_class == "binary_input"
        assert event.metric == "high_pressure_alarm"
        assert event.value is True
        assert event.point_index == 1
        assert event.quality_flags == 0x81

    def test_decode_comm_fault(self, receiver):
        record = {"group": 2, "index": 3, "value": True, "flags": 0x81}
        event = receiver._record_to_event(record)
        assert event.metric == "communication_fault"

    def test_decode_compressor_running_off(self, receiver):
        record = {"group": 2, "index": 0, "value": False, "flags": 0x01}
        event = receiver._record_to_event(record)
        assert event.metric == "compressor_running"
        assert event.value is False

    def test_unknown_binary_point_falls_back_to_generic_name(self, receiver):
        record = {"group": 2, "index": 99, "value": True, "flags": 0x01}
        event = receiver._record_to_event(record)
        assert event.metric == "binary_99"


class TestAnalogInputDecode:
    def test_decode_suction_pressure(self, receiver):
        record = {"group": 32, "index": 0, "value": 845.5, "flags": 0x01}
        event = receiver._record_to_event(record)
        assert event is not None
        assert event.event_class == "analog_input"
        assert event.metric == "suction_pressure"
        assert event.value == pytest.approx(845.5)
        assert event.unit == "PSI"

    def test_decode_battery_voltage(self, receiver):
        record = {"group": 32, "index": 5, "value": 11.9, "flags": 0x01}
        event = receiver._record_to_event(record)
        assert event.metric == "battery_voltage"
        assert event.unit == "VDC"

    def test_decode_vibration(self, receiver):
        record = {"group": 32, "index": 8, "value": 5.2, "flags": 0x01}
        event = receiver._record_to_event(record)
        assert event.metric == "vibration"
        assert event.unit == "mm/s"


class TestTimestampParsing:
    def test_datetime_timestamp_preserved(self, receiver):
        ts = datetime(2026, 5, 20, 14, 30, 0, tzinfo=UTC)
        record = {"group": 2, "index": 0, "value": True, "flags": 1, "timestamp": ts}
        event = receiver._record_to_event(record)
        assert event.device_timestamp == ts

    def test_epoch_ms_timestamp_converted(self, receiver):
        # 2026-05-20 14:30:00 UTC ≈ 1779546600000 ms
        record = {"group": 2, "index": 0, "value": True, "flags": 1, "timestamp": 1779546600000}
        event = receiver._record_to_event(record)
        assert event.device_timestamp is not None
        assert event.device_timestamp.tzinfo is not None

    def test_naive_datetime_assumed_utc(self, receiver):
        naive = datetime(2026, 5, 20, 14, 30, 0)
        record = {"group": 2, "index": 0, "value": True, "flags": 1, "timestamp": naive}
        event = receiver._record_to_event(record)
        assert event.device_timestamp.tzinfo == UTC


class TestLatencyComputation:
    def test_latency_positive(self):
        ts = datetime.now(UTC)
        event = DNP3Event(
            asset_id="RTU-01",
            event_class="binary_input",
            point_index=1,
            metric="high_pressure_alarm",
            value=True,
            device_timestamp=ts,
        )
        # received_at defaults to now() and is set after device_timestamp.
        latency = event.latency_ms
        assert latency is not None
        assert latency >= 0.0
        assert latency < 1000.0  # reasonable sanity bound

    def test_latency_none_without_device_timestamp(self):
        event = DNP3Event(
            asset_id="RTU-01",
            event_class="binary_input",
            point_index=1,
            metric="high_pressure_alarm",
            value=True,
            device_timestamp=None,
        )
        assert event.latency_ms is None

    def test_negative_clock_skew_clamps_to_zero(self):
        future = datetime.now(UTC).replace(year=2099)
        event = DNP3Event(
            asset_id="RTU-01",
            event_class="binary_input",
            point_index=1,
            metric="high_pressure_alarm",
            value=True,
            device_timestamp=future,
        )
        assert event.latency_ms == 0.0


class TestPointMapCoverage:
    def test_all_scadapack_binary_inputs_named(self):
        """Every binary point in the SCADAPack map has a metric name —
        nothing falls back to binary_N for the points we ship."""
        for idx, spec in SCADAPACK_BINARY_INPUTS.items():
            assert "metric" in spec
            assert spec["metric"].replace("_", "").isalnum()

    def test_all_scadapack_analog_inputs_have_units(self):
        for idx, spec in SCADAPACK_ANALOG_INPUTS.items():
            assert "metric" in spec
            assert "unit" in spec
