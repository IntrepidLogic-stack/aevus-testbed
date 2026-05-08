"""
Aevus Testbed --- Cisco Catalyst 2960 SNMP Collector
Polls Cisco-specific OIDs for CPU, memory, and interface stats.

Uses CISCO-PROCESS-MIB and CISCO-MEMORY-POOL-MIB for platform-specific
telemetry beyond what standard MIB-II provides.
"""

import asyncio
import contextlib
import subprocess

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Cisco-specific OIDs
CISCO_OIDS = {
    # CISCO-PROCESS-MIB: CPU utilization
    "cpu_5sec": "1.3.6.1.4.1.9.9.109.1.1.1.1.6.1",  # cpmCPUTotal5secRev
    "cpu_1min": "1.3.6.1.4.1.9.9.109.1.1.1.1.7.1",  # cpmCPUTotal1minRev
    "cpu_5min": "1.3.6.1.4.1.9.9.109.1.1.1.1.8.1",  # cpmCPUTotal5minRev
    # CISCO-MEMORY-POOL-MIB: Memory pools
    "mem_used": "1.3.6.1.4.1.9.9.48.1.1.1.5.1",  # ciscoMemoryPoolUsed (Processor)
    "mem_free": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",  # ciscoMemoryPoolFree (Processor)
    "mem_io_used": "1.3.6.1.4.1.9.9.48.1.1.1.5.2",  # ciscoMemoryPoolUsed (I/O)
    "mem_io_free": "1.3.6.1.4.1.9.9.48.1.1.1.6.2",  # ciscoMemoryPoolFree (I/O)
    # ENTITY-MIB: Hardware info
    "env_temp": "1.3.6.1.4.1.9.9.13.1.3.1.3.1",  # ciscoEnvMonTemperatureValue
}

# Standard MIB-II for interface stats (same as router collector)
INTERFACE_OIDS = {
    "if_descr": "1.3.6.1.2.1.2.2.1.2",
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8",
    "if_in_octets": "1.3.6.1.2.1.2.2.1.10",
    "if_out_octets": "1.3.6.1.2.1.2.2.1.16",
    "if_in_errors": "1.3.6.1.2.1.2.2.1.14",
    "if_out_errors": "1.3.6.1.2.1.2.2.1.20",
}

SYSTEM_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
}


class SNMPSwitchCollector(BaseCollector):
    """Collects telemetry from a Cisco Catalyst 2960 via SNMP v2c.

    Uses Cisco-specific MIBs (CISCO-PROCESS-MIB, CISCO-MEMORY-POOL-MIB)
    for accurate CPU and memory monitoring, plus standard MIB-II for
    interface counters.
    """

    def __init__(
        self,
        asset_id: str,
        host: str,
        community: str = "aevus_ro",
        poll_interval: int = 30,
    ):
        super().__init__(asset_id, host, poll_interval)
        self.community = community

    async def is_reachable(self) -> bool:
        """Check if the switch responds to SNMP."""
        value = await self._snmp_get(SYSTEM_OIDS["sys_descr"])
        return value is not None

    async def poll(self) -> list[RawTelemetry]:
        """Poll Cisco-specific CPU, memory, temperature, and interface stats."""
        readings: list[RawTelemetry] = []

        # CPU utilization (5-minute average — most useful for alerting)
        cpu_5min = await self._snmp_get(CISCO_OIDS["cpu_5min"])
        if cpu_5min is not None:
            with contextlib.suppress(ValueError):
                readings.append(
                    self._make_reading(
                        metric="cpu_load",
                        value=float(cpu_5min),
                        unit="%",
                        source="snmp",
                        oid=CISCO_OIDS["cpu_5min"],
                    )
                )

        # CPU 1-minute (for trend analysis)
        cpu_1min = await self._snmp_get(CISCO_OIDS["cpu_1min"])
        if cpu_1min is not None:
            with contextlib.suppress(ValueError):
                readings.append(
                    self._make_reading(
                        metric="cpu_load_1min",
                        value=float(cpu_1min),
                        unit="%",
                        source="snmp",
                        oid=CISCO_OIDS["cpu_1min"],
                    )
                )

        # Memory usage (Processor pool)
        mem_used = await self._snmp_get(CISCO_OIDS["mem_used"])
        mem_free = await self._snmp_get(CISCO_OIDS["mem_free"])
        if mem_used and mem_free:
            try:
                used = float(mem_used)
                free = float(mem_free)
                total = used + free
                if total > 0:
                    pct = (used / total) * 100
                    readings.append(
                        self._make_reading(
                            metric="memory_usage",
                            value=round(pct, 1),
                            unit="%",
                            source="snmp",
                        )
                    )
            except ValueError:
                pass

        # Temperature
        temp = await self._snmp_get(CISCO_OIDS["env_temp"])
        if temp is not None:
            with contextlib.suppress(ValueError):
                readings.append(
                    self._make_reading(
                        metric="temperature",
                        value=float(temp),
                        unit="C",
                        source="snmp",
                        oid=CISCO_OIDS["env_temp"],
                    )
                )

        # System uptime
        uptime_raw = await self._snmp_get(SYSTEM_OIDS["sys_uptime"])
        if uptime_raw is not None:
            try:
                ticks = float(uptime_raw.split("(")[1].split(")")[0]) if "(" in uptime_raw else float(uptime_raw)
                hours = ticks / 360000.0
                readings.append(
                    self._make_reading(
                        metric="uptime",
                        value=round(hours, 2),
                        unit="hrs",
                        source="snmp",
                        oid=SYSTEM_OIDS["sys_uptime"],
                    )
                )
            except (ValueError, IndexError):
                pass

        # Interface stats
        if_readings = await self._poll_interfaces()
        readings.extend(if_readings)

        return readings

    async def _poll_interfaces(self) -> list[RawTelemetry]:
        """Walk interface table for traffic, error counters, and link status."""
        readings: list[RawTelemetry] = []
        if_walk = await asyncio.to_thread(self._snmp_walk_sync, INTERFACE_OIDS["if_descr"])

        for if_oid, if_name in if_walk.items():
            if_index = if_oid.split(".")[-1]
            if_name_clean = if_name.strip('"').replace("STRING: ", "")

            for counter, base_oid in [
                ("in_octets", INTERFACE_OIDS["if_in_octets"]),
                ("out_octets", INTERFACE_OIDS["if_out_octets"]),
                ("in_errors", INTERFACE_OIDS["if_in_errors"]),
                ("out_errors", INTERFACE_OIDS["if_out_errors"]),
            ]:
                val = await self._snmp_get(f"{base_oid}.{if_index}")
                if val is not None:
                    with contextlib.suppress(ValueError):
                        readings.append(
                            self._make_reading(
                                metric=f"{if_name_clean}_{counter}",
                                value=float(val),
                                unit="bytes" if "octets" in counter else "count",
                                source="snmp",
                                oid=f"{base_oid}.{if_index}",
                            )
                        )

            # Interface operational status (1=up, 2=down, 3=testing)
            status_val = await self._snmp_get(f"{INTERFACE_OIDS['if_oper_status']}.{if_index}")
            if status_val is not None:
                with contextlib.suppress(ValueError):
                    readings.append(
                        self._make_reading(
                            metric=f"{if_name_clean}_oper_status",
                            value=float(status_val),
                            unit="",
                            source="snmp",
                            oid=f"{INTERFACE_OIDS['if_oper_status']}.{if_index}",
                        )
                    )

        return readings

    async def _snmp_get(self, oid: str) -> str | None:
        """Get a single OID value."""
        return await asyncio.to_thread(self._snmp_get_sync, oid)

    def _snmp_get_sync(self, oid: str) -> str | None:
        """Synchronous SNMP GET via CLI."""
        try:
            result = subprocess.run(
                ["snmpget", "-v2c", "-c", self.community, "-t", "5", "-r", "1", "-Oqv", self.host, oid],
                capture_output=True,
                text=True,
                timeout=10,
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
