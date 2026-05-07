"""Tests for the simulator collector."""

import pytest

from src.collectors.simulator import SimulatorCollector
from src.models.telemetry import RawTelemetry


class TestSimulatorCollector:
    """Tests for the SimulatorCollector."""

    @pytest.mark.asyncio
    async def test_radio_metrics(self):
        collector = SimulatorCollector("RAD-01", device_type="radio")
        readings = await collector.safe_poll()
        assert len(readings) > 0
        metrics = {r.metric for r in readings}
        assert "rssi" in metrics
        assert "snr" in metrics
        assert "temperature" in metrics

    @pytest.mark.asyncio
    async def test_rtu_metrics(self):
        collector = SimulatorCollector("RTU-01", device_type="rtu")
        readings = await collector.safe_poll()
        assert len(readings) > 0
        metrics = {r.metric for r in readings}
        assert "suction_pressure" in metrics
        assert "battery_voltage" in metrics

    @pytest.mark.asyncio
    async def test_router_metrics(self):
        collector = SimulatorCollector("RTR-01", device_type="router")
        readings = await collector.safe_poll()
        assert len(readings) > 0
        metrics = {r.metric for r in readings}
        assert "cpu_load" in metrics

    @pytest.mark.asyncio
    async def test_readings_are_raw_telemetry(self):
        collector = SimulatorCollector("RAD-01", device_type="radio")
        readings = await collector.safe_poll()
        for r in readings:
            assert isinstance(r, RawTelemetry)
            assert r.asset_id == "RAD-01"
            assert r.source == "simulator"
            assert isinstance(r.value, float)

    @pytest.mark.asyncio
    async def test_readings_have_timestamps(self):
        collector = SimulatorCollector("RAD-01", device_type="radio")
        readings = await collector.safe_poll()
        for r in readings:
            assert r.timestamp is not None

    def test_poll_interval_default(self):
        collector = SimulatorCollector("RAD-01", device_type="radio")
        assert collector.poll_interval == 5

    def test_poll_interval_override(self):
        collector = SimulatorCollector("RAD-01", device_type="radio")
        collector.poll_interval = 10
        assert collector.poll_interval == 10
