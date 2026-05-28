"""
Aevus Testbed — Trio JR900 SNMP Collector
Polls Trio Datacom JR900 radios via SNMP v2c.

Enterprise OID: 1.3.6.1.4.1.33302
Discovered via live SNMP walk on JR900-00002-EH0, Firmware 3.8.4
"""

import asyncio
import subprocess

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Trio JR900 enterprise OIDs (enterprise: 1.3.6.1.4.1.33302)
TRIO_ENTERPRISE = "1.3.6.1.4.1.33302"

# System info OIDs (10.1.x)
TRIO_SYSTEM_OIDS = {
    "serial_number":   f"{TRIO_ENTERPRISE}.10.1.1.0",
    "model":           f"{TRIO_ENTERPRISE}.10.1.2.0",
    "hw_revision":     f"{TRIO_ENTERPRISE}.10.1.3.0",
    "frequency_band":  f"{TRIO_ENTERPRISE}.10.1.4.0",
    "firmware":        f"{TRIO_ENTERPRISE}.10.1.5.0",
    "uptime_str":      f"{TRIO_ENTERPRISE}.10.1.9.0",
    "voltage_mv":      f"{TRIO_ENTERPRISE}.10.1.12.0",
    "temperature":     f"{TRIO_ENTERPRISE}.10.1.13.0",
    "signal_quality":  f"{TRIO_ENTERPRISE}.10.1.14.0",
    "ip_address":      f"{TRIO_ENTERPRISE}.10.1.15.0",
}

# Radio link OIDs (10.2.x)
TRIO_RADIO_OIDS = {
    "radio_type":      f"{TRIO_ENTERPRISE}.10.2.1.0",      # 1=AP, 2=Remote
    "network_id":      f"{TRIO_ENTERPRISE}.10.2.2.1.2.1",  # e.g. "killdeer"
    "tx_packets":      f"{TRIO_ENTERPRISE}.10.2.3.0",
    "rx_packets":      f"{TRIO_ENTERPRISE}.10.2.4.0",
    "tx_power":        f"{TRIO_ENTERPRISE}.10.2.5.1.2.1",  # dBm
    "rssi":            f"{TRIO_ENTERPRISE}.10.2.8.1.2.1",  # dBm
    "link_state":      f"{TRIO_ENTERPRISE}.10.2.10.0",     # 1=linked
    "tx_error":        f"{TRIO_ENTERPRISE}.10.2.11.0",
    "rx_error":        f"{TRIO_ENTERPRISE}.10.2.12.0",
    "rx_dropped":      f"{TRIO_ENTERPRISE}.10.2.13.0",
}

# All polled metrics with units
TRIO_POLL_OIDS = {
    "voltage":         (f"{TRIO_ENTERPRISE}.10.1.12.0", "mV"),
    "temperature":     (f"{TRIO_ENTERPRISE}.10.1.13.0", "°C"),
    "signal_quality":  (f"{TRIO_ENTERPRISE}.10.1.14.0", "%"),
    "rssi":            (f"{TRIO_ENTERPRISE}.10.2.8.1.2.1", "dBm"),
    "tx_power":        (f"{TRIO_ENTERPRISE}.10.2.5.1.2.1", "dBm"),
    "tx_packets":      (f"{TRIO_ENTERPRISE}.10.2.3.0", "count"),
    "rx_packets":      (f"{TRIO_ENTERPRISE}.10.2.4.0", "count"),
    "tx_error":        (f"{TRIO_ENTERPRISE}.10.2.11.0", "count"),
    "rx_error":        (f"{TRIO_ENTERPRISE}.10.2.12.0", "count"),
    "rx_dropped":      (f"{TRIO_ENTERPRISE}.10.2.13.0", "count"),
    "link_state":      (f"{TRIO_ENTERPRISE}.10.2.10.0", ""),
}

# Standard MIB-II OIDs
STANDARD_OIDS = {
    "sys_descr":    "1.3.6.1.2.1.1.1.0",
    "sys_name":     "1.3.6.1.2.1.1.5.0",
    "sys_uptime":   "1.3.6.1.2.1.1.3.0",
    "sys_location": "1.3.6.1.2.1.1.6.0",
}


class TrioJR900Collector(BaseCollector):
    """Collects telemetry from a Trio JR900 radio via SNMP v2c."""

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
        """Check if the radio responds to SNMP sysDescr query."""
        value = await self._snmp_get(STANDARD_OIDS["sys_descr"])
        return value is not None

    async def poll(self) -> list[RawTelemetry]:
        """Poll all Trio JR900 OIDs and return raw telemetry readings."""
        readings: list[RawTelemetry] = []

        # Capture firmware (Trio MIB 10.1.5.0, e.g. "3.8.4 Build 4104") for
        # FirmwareTracker + the Asset.firmware field surfaced on the dashboard.
        fw = await self._snmp_get(TRIO_SYSTEM_OIDS["firmware"])
        if fw:
            self.firmware_version = fw.strip().strip('"')

        for metric, (oid, unit) in TRIO_POLL_OIDS.items():
            value = await self._snmp_get(oid)
            if value is not None:
                try:
                    numeric_value = float(value)
                    # Convert voltage from mV to V for display
                    if metric == "voltage":
                        numeric_value = numeric_value / 1000.0
                        unit = "V"
                    readings.append(
                        self._make_reading(
                            metric=metric,
                            value=numeric_value,
                            unit=unit,
                            source="snmp",
                            oid=oid,
                        )
                    )
                except (ValueError, TypeError):
                    self.log.warning("non_numeric_oid", metric=metric, oid=oid, raw=value)

        return readings

    async def get_system_info(self) -> dict[str, str]:
        """Get radio system information (serial, model, firmware, etc)."""
        info = {}
        for key, oid in TRIO_SYSTEM_OIDS.items():
            value = await self._snmp_get(oid)
            if value:
                info[key] = value.strip('"')
        return info

    async def get_radio_status(self) -> dict[str, str]:
        """Get radio link status (type, network ID, link state)."""
        status = {}
        for key, oid in TRIO_RADIO_OIDS.items():
            value = await self._snmp_get(oid)
            if value:
                status[key] = value.strip('"')
        return status

    async def snmp_walk(self) -> dict[str, str]:
        """Full SNMP walk — used for discovery, not regular polling."""
        return await asyncio.to_thread(self._snmp_walk_sync)

    async def _snmp_get(self, oid: str) -> str | None:
        """Get a single OID value via snmpget CLI."""
        return await asyncio.to_thread(self._snmp_get_sync, oid)

    def _snmp_get_sync(self, oid: str) -> str | None:
        """Synchronous SNMP GET using snmpget CLI tool."""
        try:
            result = subprocess.run(
                [
                    "snmpget",
                    "-v2c",
                    "-c",
                    self.community,
                    "-t",
                    "5",
                    "-r",
                    "1",
                    "-Oqv",
                    self.host,
                    oid,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            raw = result.stdout.strip()
            if ": " in raw:
                raw = raw.split(": ", 1)[1]
            raw = raw.strip('"')
            return raw

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.log.warning("snmp_get_failed", oid=oid, error=str(e))
            return None

    def _snmp_walk_sync(self) -> dict[str, str]:
        """Synchronous full SNMP walk for device discovery."""
        try:
            result = subprocess.run(
                [
                    "snmpwalk",
                    "-v2c",
                    "-c",
                    self.community,
                    "-t",
                    "10",
                    self.host,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return {}

            oids: dict[str, str] = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    parts = line.split("=", 1)
                    oid = parts[0].strip()
                    value = parts[1].strip() if len(parts) > 1 else ""
                    oids[oid] = value
            return oids

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}
