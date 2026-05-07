"""
Aevus Testbed — Trio JR900 SNMP Collector
Polls Trio Datacom JR900 radios via SNMP v2c.

Enterprise OID: 1.3.6.1.4.1.5727
"""

import asyncio
import subprocess

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

# Trio JR900 SNMP OID map (enterprise: 1.3.6.1.4.1.5727)
TRIO_OIDS = {
    "rssi": "1.3.6.1.4.1.5727.1.1.1.0",
    "snr": "1.3.6.1.4.1.5727.1.1.2.0",
    "tx_power": "1.3.6.1.4.1.5727.1.2.1.0",
    "modulation": "1.3.6.1.4.1.5727.1.2.2.0",
    "rx_packets": "1.3.6.1.4.1.5727.1.3.1.0",
    "tx_packets": "1.3.6.1.4.1.5727.1.3.2.0",
    "error_packets": "1.3.6.1.4.1.5727.1.3.3.0",
    "temperature": "1.3.6.1.4.1.5727.1.4.1.0",
    "voltage": "1.3.6.1.4.1.5727.1.4.2.0",
}

# Standard MIB OIDs (works on any SNMP device)
STANDARD_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8.1",
}

METRIC_UNITS = {
    "rssi": "dBm",
    "snr": "dB",
    "tx_power": "dBm",
    "modulation": "",
    "rx_packets": "count",
    "tx_packets": "count",
    "error_packets": "count",
    "temperature": "°C",
    "voltage": "V",
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

        for metric, oid in TRIO_OIDS.items():
            value = await self._snmp_get(oid)
            if value is not None:
                try:
                    numeric_value = float(value)
                    readings.append(
                        self._make_reading(
                            metric=metric,
                            value=numeric_value,
                            unit=METRIC_UNITS.get(metric, ""),
                            source="snmp",
                            oid=oid,
                        )
                    )
                except (ValueError, TypeError):
                    self.log.warning("non_numeric_oid", metric=metric, oid=oid, raw=value)

        return readings

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
                    "5",  # timeout seconds
                    "-r",
                    "1",  # retries
                    "-Oqv",  # quiet, value-only output
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
            # Strip SNMP type prefixes like "INTEGER: ", "STRING: ", etc.
            if ": " in raw:
                raw = raw.split(": ", 1)[1]
            # Strip quotes from string values
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
