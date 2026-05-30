"""
Aevus Testbed — MikroTik L009 SNMP Collector
Polls MikroTik RouterOS via SNMP v2c using standard MIB-II OIDs.

This collector also serves as the base for Cisco Catalyst 2960 polling
since both use standard SNMP MIBs for interface statistics.
"""

import asyncio
import subprocess

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Standard MIB-II OIDs (work on MikroTik, Cisco, any SNMP device)
SYSTEM_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
    "sys_contact": "1.3.6.1.2.1.1.4.0",
    "sys_location": "1.3.6.1.2.1.1.6.0",
}

# Interface table OIDs — append .<ifIndex> for specific interface
INTERFACE_OIDS = {
    "if_descr": "1.3.6.1.2.1.2.2.1.2",  # Interface description
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8",  # 1=up, 2=down
    "if_in_octets": "1.3.6.1.2.1.2.2.1.10",  # Bytes received
    "if_out_octets": "1.3.6.1.2.1.2.2.1.16",  # Bytes transmitted
    "if_in_errors": "1.3.6.1.2.1.2.2.1.14",  # Input errors
    "if_out_errors": "1.3.6.1.2.1.2.2.1.20",  # Output errors
}

# MikroTik-specific OIDs (RouterOS SNMP extension)
MIKROTIK_OIDS = {
    "cpu_load": "1.3.6.1.2.1.25.3.3.1.2.1",  # hrProcessorLoad
    "total_memory": "1.3.6.1.2.1.25.2.3.1.5.65536",  # hrStorageSize
    "used_memory": "1.3.6.1.2.1.25.2.3.1.6.65536",  # hrStorageUsed
}

# Cisco IOS-specific OIDs (CISCO-PROCESS-MIB + CISCO-MEMORY-POOL-MIB)
# Verified against Catalyst 2960 / IOS 15.0(2)SE11 on 2026-05-26.
CISCO_OIDS = {
    "cpu_load": "1.3.6.1.4.1.9.9.109.1.1.1.1.7.1",  # cpmCPUTotal1min, processor index 1
    "memory_used": "1.3.6.1.4.1.9.9.48.1.1.1.5.1",  # ciscoMemoryPoolUsed, pool 1 (Processor)
    "memory_free": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",  # ciscoMemoryPoolFree, pool 1
}

# ── Tier 1 (2026-05-27): expanded SCADA telemetry ──────────────────────

# CDP — Cisco Discovery Protocol neighbor table (works on Catalyst + MikroTik if enabled)
# Walking these OIDs returns one entry per CDP neighbor:
#   .1.6 = neighbor sysName (deviceId)
#   .1.4 = neighbor IP address
#   .1.7 = neighbor port (device port on the other side)
CDP_NEIGHBOR_OIDS = {
    "cdp_device_id": "1.3.6.1.4.1.9.9.23.1.2.1.1.6",  # cdpCacheDeviceId
    "cdp_device_port": "1.3.6.1.4.1.9.9.23.1.2.1.1.7",  # cdpCacheDevicePort
    "cdp_platform": "1.3.6.1.4.1.9.9.23.1.2.1.1.8",  # cdpCachePlatform
}

# Per-port physical layer health
PORT_HEALTH_OIDS = {
    "if_speed": "1.3.6.1.2.1.2.2.1.5",  # ifSpeed (bits/sec)
    "if_in_discards": "1.3.6.1.2.1.2.2.1.13",  # ifInDiscards
    "if_out_discards": "1.3.6.1.2.1.2.2.1.19",  # ifOutDiscards
}

# MikroTik hardware sensors (CPU temp, voltage)
MIKROTIK_HW_OIDS = {
    "board_temperature": "1.3.6.1.4.1.14988.1.1.3.100.1.3.17",  # cpu-temperature value
    "board_temp_label": "1.3.6.1.4.1.14988.1.1.3.100.1.2.17",  # sensor name
    "board_voltage": "1.3.6.1.4.1.14988.1.1.3.11.0",  # mtxrHlVoltage (decivolts)
    "board_total_mem": "1.3.6.1.4.1.14988.1.1.3.14.0",  # mtxrHlActiveFan (or memory — varies by model)
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

        # Capture sys_descr (firmware/OS version string) for FirmwareTracker.
        # Strip the "STRING: " SNMP type prefix if present.
        sys_descr = await self._snmp_get(SYSTEM_OIDS["sys_descr"])
        if sys_descr:
            self.firmware_version = sys_descr.replace("STRING: ", "").strip().strip('"')

        # CPU load + memory usage — vendor-specific OIDs
        if self.device_type == "switch":
            # Cisco IOS path
            cpu = await self._snmp_get(CISCO_OIDS["cpu_load"])
            if cpu is not None:
                try:
                    readings.append(
                        self._make_reading(
                            metric="cpu_load",
                            value=float(cpu),
                            unit="%",
                            source="snmp",
                            oid=CISCO_OIDS["cpu_load"],
                        )
                    )
                except ValueError:
                    pass

            used_mem = await self._snmp_get(CISCO_OIDS["memory_used"])
            free_mem = await self._snmp_get(CISCO_OIDS["memory_free"])
            if used_mem and free_mem:
                try:
                    used = float(used_mem)
                    free = float(free_mem)
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
        else:
            # MikroTik / generic RouterOS path
            cpu = await self._snmp_get(MIKROTIK_OIDS["cpu_load"])
            if cpu is not None:
                try:
                    readings.append(
                        self._make_reading(
                            metric="cpu_load",
                            value=float(cpu),
                            unit="%",
                            source="snmp",
                            oid=MIKROTIK_OIDS["cpu_load"],
                        )
                    )
                except ValueError:
                    pass

            total_mem = await self._snmp_get(MIKROTIK_OIDS["total_memory"])
            used_mem = await self._snmp_get(MIKROTIK_OIDS["used_memory"])
            if total_mem and used_mem:
                try:
                    total = float(total_mem)
                    used = float(used_mem)
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

        # System uptime (hundredths of seconds → hours)
        uptime_raw = await self._snmp_get(SYSTEM_OIDS["sys_uptime"])
        if uptime_raw is not None:
            try:
                # uptime comes as timeticks (hundredths of a second)
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

        # Interface stats — walk the interface table
        if_readings = await self._poll_interfaces()
        readings.extend(if_readings)

        # Tier 1 (2026-05-27): CDP neighbors, per-port speed/discards, MikroTik HW sensors
        try:
            readings.extend(await self._poll_cdp_neighbors())
        except Exception:
            pass  # CDP not supported / disabled — skip silently
        try:
            readings.extend(await self._poll_port_health())
        except Exception:
            pass
        if self.device_type == "router":
            try:
                readings.extend(await self._poll_mikrotik_hardware())
            except Exception:
                pass

        return readings

    async def _poll_cdp_neighbors(self):
        """Count CDP neighbors. Cisco devices return neighbor names in CDP
        cache; we only emit a numeric count here because RawTelemetry
        requires a float value. Neighbor names will move to a separate
        non-numeric path later (events_json or /api/v1/diagnostics/topology)."""
        readings = []
        try:
            neighbors = await asyncio.to_thread(self._snmp_walk_sync, CDP_NEIGHBOR_OIDS["cdp_device_id"])
        except Exception:
            return readings
        count = sum(1 for _, v in (neighbors or {}).items() if self._parse_snmp_walk_value(v))
        if count > 0:
            try:
                readings.append(
                    self._make_reading(
                        metric="cdp_neighbor_count",
                        value=float(count),
                        unit="count",
                        source="snmp",
                        oid=CDP_NEIGHBOR_OIDS["cdp_device_id"],
                    )
                )
            except Exception:
                pass
        return readings

    async def _poll_port_health(self) -> list[RawTelemetry]:
        """Per-port speed + discards. Most physical-layer SCADA outages
        manifest first as discard counter increases (silent packet drop)
        long before they cross the if-errors threshold."""
        readings: list[RawTelemetry] = []
        try:
            speeds = await asyncio.to_thread(self._snmp_walk_sync, PORT_HEALTH_OIDS["if_speed"])
        except Exception:
            return readings
        for oid, speed_raw in (speeds or {}).items():
            if_index = oid.split(".")[-1]
            try:
                bps = float(self._parse_snmp_walk_value(speed_raw))
                if bps == 0:
                    continue  # admin-down port, skip
                mbps = bps / 1_000_000.0
                readings.append(
                    self._make_reading(
                        metric=f"port_{if_index}_speed",
                        value=round(mbps, 1),
                        unit="Mbps",
                        source="snmp",
                    )
                )
            except (ValueError, TypeError):
                pass
        # Discards
        for direction, oid_base in [
            ("in", PORT_HEALTH_OIDS["if_in_discards"]),
            ("out", PORT_HEALTH_OIDS["if_out_discards"]),
        ]:
            try:
                discards = await asyncio.to_thread(self._snmp_walk_sync, oid_base)
            except Exception:
                continue
            for oid, v in (discards or {}).items():
                if_index = oid.split(".")[-1]
                try:
                    n = float(self._parse_snmp_walk_value(v))
                    if n > 0:  # only surface non-zero discards (avoid noise)
                        readings.append(
                            self._make_reading(
                                metric=f"port_{if_index}_{direction}_discards",
                                value=n,
                                unit="count",
                                source="snmp",
                            )
                        )
                except (ValueError, TypeError):
                    pass
        return readings

    async def _poll_mikrotik_hardware(self) -> list[RawTelemetry]:
        """MikroTik board sensors — CPU temperature + voltage.
        Voltage sag is one of the strongest predictors of PSU failure.
        Only called when device_type == 'router' AND vendor likely-MikroTik."""
        readings: list[RawTelemetry] = []
        # board temperature (sensor index 17 on L009 = cpu-temperature)
        t = await self._snmp_get(MIKROTIK_HW_OIDS["board_temperature"])
        if t is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="board_temperature",
                        value=float(str(t).strip().strip('"')),
                        unit="°C",
                        source="snmp",
                        oid=MIKROTIK_HW_OIDS["board_temperature"],
                    )
                )
            except (ValueError, TypeError):
                pass
        # board voltage (decivolts → volts)
        v = await self._snmp_get(MIKROTIK_HW_OIDS["board_voltage"])
        if v is not None:
            try:
                volts = float(str(v).strip().strip('"')) / 10.0
                readings.append(
                    self._make_reading(
                        metric="board_voltage",
                        value=round(volts, 1),
                        unit="V",
                        source="snmp",
                        oid=MIKROTIK_HW_OIDS["board_voltage"],
                    )
                )
            except (ValueError, TypeError):
                pass
        return readings

    async def _poll_interfaces(self) -> list[RawTelemetry]:
        """Walk interface table for traffic and error counters."""
        readings: list[RawTelemetry] = []

        # Get interface descriptions to identify ports
        if_walk = await asyncio.to_thread(self._snmp_walk_sync, INTERFACE_OIDS["if_descr"])

        for if_oid, if_name in if_walk.items():
            # Extract interface index from OID
            if_index = if_oid.split(".")[-1]
            if_name_clean = self._parse_snmp_walk_value(if_name)

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
                        readings.append(
                            self._make_reading(
                                metric=f"{if_name_clean}_{counter}",
                                value=float(val),
                                unit="bytes" if "octets" in counter else "count",
                                source="snmp",
                                oid=f"{base_oid}.{if_index}",
                            )
                        )
                    except ValueError:
                        pass

            # Oper status
            status_val = await self._snmp_get(f"{INTERFACE_OIDS['if_oper_status']}.{if_index}")
            if status_val is not None:
                try:
                    readings.append(
                        self._make_reading(
                            metric=f"{if_name_clean}_oper_status",
                            value=float(status_val),
                            unit="",  # 1=up, 2=down
                            source="snmp",
                            oid=f"{INTERFACE_OIDS['if_oper_status']}.{if_index}",
                        )
                    )
                except ValueError:
                    pass

        return readings

    async def snmp_walk(self) -> dict[str, str]:
        """Full SNMP walk for discovery."""
        return await asyncio.to_thread(self._snmp_walk_sync)

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

    def _parse_snmp_walk_value(self, raw):
        """Strip SNMP type prefix from snmpwalk values.
        snmpwalk emits values like 'STRING: "x"', 'Gauge32: 123', 'Counter32: 0'.
        This helper returns just the value, no prefix, no surrounding quotes."""
        if raw is None:
            return ""
        s = str(raw).strip().strip('"')
        for prefix in (
            "STRING:",
            "Gauge32:",
            "Counter32:",
            "Counter64:",
            "INTEGER:",
            "Timeticks:",
            "Hex-STRING:",
            "OID:",
            "IpAddress:",
        ):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip().strip('"')
                break
        return s

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
