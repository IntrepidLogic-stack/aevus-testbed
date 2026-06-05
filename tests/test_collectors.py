"""Tests for the simulator collector."""

from unittest.mock import AsyncMock, patch

import pytest

from src.collectors.simulator import SimulatorCollector
from src.collectors.snmp_router import SYSTEM_OIDS, SNMPNetworkCollector
from src.models.telemetry import RawTelemetry

# Real Catalyst 2960 sysDescr banner — the live SW-01 polling path runs through
# SNMPNetworkCollector(device_type="switch"), so firmware parsing is verified here too.
CATALYST_SYS_DESCR = (
    "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11, "
    "RELEASE SOFTWARE (fc3) Technical Support: http://www.cisco.com/techsupport "
    "Copyright (c) 1986-2017 by Cisco Systems, Inc. Compiled Sat 19-Aug-17 09:34 "
    "by prod_rel_team"
)


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


class TestSNMPNetworkCollectorFirmware:
    """Firmware parsing for the live SW-01 path (SNMPNetworkCollector switch mode)."""

    @pytest.mark.asyncio
    async def test_switch_firmware_is_clean_version(self):
        """SW-01 should report the IOS version token, not the full sysDescr banner."""
        collector = SNMPNetworkCollector("SW-01", "192.168.88.2", device_type="switch")

        async def mock_get(oid):
            if oid == SYSTEM_OIDS["sys_descr"]:
                return CATALYST_SYS_DESCR
            return None

        with (
            patch.object(collector, "_snmp_get", side_effect=mock_get),
            patch.object(collector, "_poll_interfaces", new_callable=AsyncMock, return_value=[]),
        ):
            await collector.poll()

        assert collector.firmware_version == "15.0(2)SE11"

    @pytest.mark.asyncio
    async def test_router_firmware_falls_back_to_raw(self):
        """MikroTik sysDescr has no Version token, so the cleaned raw value is kept."""
        collector = SNMPNetworkCollector("RTR-01", "192.168.88.1", device_type="router")
        descr = "RouterOS RB750Gr3"

        async def mock_get(oid):
            if oid == SYSTEM_OIDS["sys_descr"]:
                return descr
            return None

        with (
            patch.object(collector, "_snmp_get", side_effect=mock_get),
            patch.object(collector, "_poll_interfaces", new_callable=AsyncMock, return_value=[]),
            patch.object(collector, "_poll_cdp_neighbors", new_callable=AsyncMock, return_value=[]),
            patch.object(collector, "_poll_port_health", new_callable=AsyncMock, return_value=[]),
            patch.object(collector, "_poll_mikrotik_hardware", new_callable=AsyncMock, return_value=[]),
        ):
            await collector.poll()

        assert collector.firmware_version == "RouterOS RB750Gr3"
