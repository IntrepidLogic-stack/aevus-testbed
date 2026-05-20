"""
Aevus Testbed — MikroTik L009 SNMP Collector
Polls MikroTik RouterOS via SNMP v2c using standard MIB-II OIDs.

This collector also serves as the base for Cisco Catalyst 2960 polling
since both use standard SNMP MIBs for interface statistics.
"""

import asyncio
import subprocess
from typing import Optional

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Standard MIB-II OIDs (work on MikroTik, Cisco, any SNMP device)
SYSTEM_OIDS = {
    "sys_descr":   "1.3.6.1.2.1.1.1.0",
    "sys_name":    "1.3.6.1.2.1.1.5.0",
    "sys_uptime":  "1.3.6.1.2.1.1.3.0",
    "sys_contact": "1.3.6.1.2.1.1.4.0",
    "sys_location": "1.3.6.1.2.1.1.6.0",
}

# Interface table OIDs — append .<ifIndex> for specific interface
INTERFACE_OIDS = {
    "if_descr":       "1.3.6.1.2.1.2.2.1.2",       # Interface description
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8",       # 1=up, 2=down
    "if_in_octets":   "1.3.6.1.2.1.2.2.1.10",      # Bytes received
    "if_out_octets":  "1.3.6.1.2.1.2.2.1.16",      # Bytes transmitted
    "if_in_errors":   "1.3.6.1.2.1.2.2.1.14",      # Input errors
    "if_out_errors":  "1.3.6.1.2.1.2.2.1.20",      # Output errors
}

# MikroTik-specific OIDs (RouterOS SNMP extension)
MIKROTIK_OIDS = {
    "cpu_load":        "1.3.6.1.2.1.25.3.3.1.2.1",   # hrProcessorLoad
    "total_memory":    "1.3.6.1.2.1.25.2.3.1.5.65536",  # hrStorageSize
    "used_memory":     "1.3.6.1.2.1.25.2.3.1.6.65536",  # hrStorageUsed
}


class SNMPNetworkCollector(BaseCollector):
    """Collects telemetry from a network device (MikroTik or Cisco) via SNMP v2c."""

    # Only the stable, always-present metrics are listed here. Per-interface
    # counters are intentionally excluded — interface presence is dynamic
    # and an admin-down port is not a partial-telemetry fault.
    expected_metrics = frozenset({"cpu_load", "memory_usage", "uptime"})

    def __init__(
        self,
        asset_id: str,
        host: str,
        community: str = "aevus_ro",
        poll_interval: int = 30,
        device_type: str = "router",  # "router" or "switch"
    ):
        super().__init__(asset_id, host, poll_interval)
        self.community = community
        self.device_type = device_type

    async def is_reachable(self) -> bool:
        """Check if the device responds to SNMP sysDescr query."""
        value = await self._snmp_get(SYSTEM_OIDS["sys_descr"])
        return value is not None

    async def poll(self) -> list[RawTelemetry]:
        """Poll system info, CPU, memory, and interface stats."""
        readings: list[RawTelemetry] = []

        # CPU load
        cpu = await self._snmp_get(MIKROTIK_OIDS["cpu_load"])
        if cpu is not None:
            try:
                readings.append(self._make_reading(
                    metric="cpu_load", value=float(cpu), unit="%",
                    source="snmp", oid=MIKROTIK_OIDS["cpu_load"],
                ))
            except ValueError:
                pass

        # Memory usage
        total_mem = await self._snmp_get(MIKROTIK_OIDS["total_memory"])
        used_mem = await self._snmp_get(MIKROTIK_OIDS["used_memory"])
        if total_mem and used_mem:
            try:
                total = float(total_mem)
                used = float(used_mem)
                if total > 0:
                    pct = (used / total) * 100
                    readings.append(self._make_reading(
                        metric="memory_usage", value=round(pct, 1), unit="%",
                        source="snmp",
                    ))
            except ValueError:
                pass

        # System uptime (hundredths of seconds → hours)
        uptime_raw = await self._snmp_get(SYSTEM_OIDS["sys_uptime"])
        if uptime_raw is not None:
            try:
                # uptime comes as timeticks (hundredths of a second)
                ticks = float(uptime_raw.split("(")[1].split(")")[0]) if "(" in uptime_raw else float(uptime_raw)
                hours = ticks / 360000.0
                readings.append(self._make_reading(
                    metric="uptime", value=round(hours, 2), unit="hrs",
                    source="snmp", oid=SYSTEM_OIDS["sys_uptime"],
                ))
            except (ValueError, IndexError):
                pass

        # Interface stats — walk the interface table
        if_readings = await self._poll_interfaces()
        readings.extend(if_readings)

        return readings

    async def _poll_interfaces(self) -> list[RawTelemetry]:
        """Walk interface table for traffic and error counters."""
        readings: list[RawTelemetry] = []

        # Get interface descriptions to identify ports
        if_walk = await asyncio.to_thread(self._snmp_walk_sync, INTERFACE_OIDS["if_descr"])

        for if_oid, if_name in if_walk.items():
            # Extract interface index from OID
            if_index = if_oid.split(".")[-1]
            if_name_clean = if_name.strip('"').replace("STRING: ", "")

            # Get counters for this interface
            for counter, base_oid in [
                ("in_octets", INTERFACE_OIDS["if_in_octets"]),
                ("out_octets", INTERFACE_OIDS["if_out_octets"]),
                ("in_errors", INTERFACE_OIDS["if_in_errors"]),
                ("out_errors", INTERFACE_OIDS["if_out_errors"]),
            ]:
                val = await self._snmp_get(f"{base_oid}.{if_index}")
                if val is not None:
                    try:
                        readings.append(self._make_reading(
                            metric=f"{if_name_clean}_{counter}",
                            value=float(val),
                            unit="bytes" if "octets" in counter else "count",
                            source="snmp",
                            oid=f"{base_oid}.{if_index}",
                        ))
                    except ValueError:
                        pass

            # Oper status
            status_val = await self._snmp_get(f"{INTERFACE_OIDS['if_oper_status']}.{if_index}")
            if status_val is not None:
                try:
                    readings.append(self._make_reading(
                        metric=f"{if_name_clean}_oper_status",
                        value=float(status_val),
                        unit="",  # 1=up, 2=down
                        source="snmp",
                        oid=f"{INTERFACE_OIDS['if_oper_status']}.{if_index}",
                    ))
                except ValueError:
                    pass

        return readings

    async def snmp_walk(self) -> dict[str, str]:
        """Full SNMP walk for discovery."""
        return await asyncio.to_thread(self._snmp_walk_sync)

    async def _snmp_get(self, oid: str) -> Optional[str]:
        """Get a single OID value."""
        return await asyncio.to_thread(self._snmp_get_sync, oid)

    def _snmp_get_sync(self, oid: str) -> Optional[str]:
        """Synchronous SNMP GET via CLI."""
        try:
            result = subprocess.run(
                ["snmpget", "-v2c", "-c", self.community, "-t", "5", "-r", "1", "-Oqv", self.host, oid],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            raw = result.stdout.strip()
            if ": " in raw:
                raw = raw.split(": ", 1)[1]
            return raw.strip('"')
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _snmp_walk_sync(self, base_oid: str = "") -> dict[str, str]:
        """Synchronous SNMP walk."""
        cmd = ["snmpwalk", "-v2c", "-c", self.community, "-t", "10", self.host]
        if base_oid:
            cmd.append(base_oid)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or not result.stdout.strip():
                return {}
            oids: dict[str, str] = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    parts = line.split("=", 1)
                    oids[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""
            return oids
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}
