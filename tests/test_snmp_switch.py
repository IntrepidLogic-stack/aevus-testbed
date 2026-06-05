"""Tests for SNMPSwitchCollector."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.collectors.snmp_switch import CISCO_OIDS, SYSTEM_OIDS, SNMPSwitchCollector

# Real Catalyst 2960 sysDescr banner captured from the lab switch.
CATALYST_SYS_DESCR = (
    "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11, "
    "RELEASE SOFTWARE (fc3) Technical Support: http://www.cisco.com/techsupport "
    "Copyright (c) 1986-2017 by Cisco Systems, Inc. Compiled Sat 19-Aug-17 09:34 "
    "by prod_rel_team"
)


@pytest.fixture
def collector():
    return SNMPSwitchCollector(
        asset_id="SW-TEST",
        host="192.168.1.1",
        community="public",
        poll_interval=30,
    )


def test_collector_init(collector):
    assert collector.asset_id == "SW-TEST"
    assert collector.host == "192.168.1.1"
    assert collector.community == "public"
    assert collector.poll_interval == 30


def test_cisco_oids_defined():
    """Verify Cisco-specific OIDs are correctly defined."""
    assert "cpu_5min" in CISCO_OIDS
    assert "mem_used" in CISCO_OIDS
    assert "mem_free" in CISCO_OIDS
    assert "env_temp" in CISCO_OIDS
    # cpmCPUTotal5minRev
    assert CISCO_OIDS["cpu_5min"] == "1.3.6.1.4.1.9.9.109.1.1.1.1.8.1"
    # ciscoMemoryPoolUsed (Processor)
    assert CISCO_OIDS["mem_used"] == "1.3.6.1.4.1.9.9.48.1.1.1.5.1"


@pytest.mark.asyncio
async def test_is_reachable_true(collector):
    with patch.object(collector, "_snmp_get", new_callable=AsyncMock, return_value="Cisco IOS"):
        assert await collector.is_reachable() is True


@pytest.mark.asyncio
async def test_is_reachable_false(collector):
    with patch.object(collector, "_snmp_get", new_callable=AsyncMock, return_value=None):
        assert await collector.is_reachable() is False


@pytest.mark.asyncio
async def test_poll_cpu_memory(collector):
    """Test polling returns CPU and memory readings."""

    async def mock_get(oid):
        return {
            CISCO_OIDS["cpu_5min"]: "12",
            CISCO_OIDS["cpu_1min"]: "15",
            CISCO_OIDS["mem_used"]: "50000000",
            CISCO_OIDS["mem_free"]: "50000000",
            CISCO_OIDS["env_temp"]: "35",
        }.get(oid)

    with (
        patch.object(collector, "_snmp_get", side_effect=mock_get),
        patch.object(collector, "_poll_interfaces", new_callable=AsyncMock, return_value=[]),
    ):
        readings = await collector.poll()

    metrics = [r.metric for r in readings]
    assert "cpu_load" in metrics
    assert "memory_usage" in metrics
    assert "temperature" in metrics

    cpu = next(r for r in readings if r.metric == "cpu_load")
    assert cpu.value == 12.0

    mem = next(r for r in readings if r.metric == "memory_usage")
    assert mem.value == 50.0  # 50M used / 100M total


@pytest.mark.asyncio
async def test_poll_handles_missing_data(collector):
    """Test poll gracefully handles missing SNMP responses."""
    with (
        patch.object(collector, "_snmp_get", new_callable=AsyncMock, return_value=None),
        patch.object(collector, "_poll_interfaces", new_callable=AsyncMock, return_value=[]),
    ):
        readings = await collector.poll()
    assert readings == []


def test_parse_firmware_version_cisco_banner(collector):
    """The full Cisco sysDescr banner is reduced to just the IOS version token."""
    assert collector._parse_firmware_version(CATALYST_SYS_DESCR) == "15.0(2)SE11"


def test_parse_firmware_version_strips_snmp_prefix(collector):
    """A 'STRING: ...' SNMP type prefix is stripped before parsing."""
    assert collector._parse_firmware_version(f"STRING: {CATALYST_SYS_DESCR}") == "15.0(2)SE11"


def test_parse_firmware_version_fallback_to_raw(collector):
    """Without a 'Version <x>' token, the cleaned raw value is returned (e.g. MikroTik)."""
    mikrotik = "RouterOS RB750Gr3"
    assert collector._parse_firmware_version(mikrotik) == "RouterOS RB750Gr3"


def test_parse_firmware_version_none(collector):
    """Empty / missing sysDescr yields None."""
    assert collector._parse_firmware_version(None) is None
    assert collector._parse_firmware_version("") is None


@pytest.mark.asyncio
async def test_poll_sets_clean_firmware(collector):
    """poll() captures sysDescr and stores only the clean version on firmware_version."""

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
