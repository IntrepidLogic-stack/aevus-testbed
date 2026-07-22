"""
Aevus Testbed — Raspberry Pi Edge Collector SNMP
Polls the Raspberry Pi (IntrepidRAS) via SNMP v2c for system health metrics.
Uses standard HOST-RESOURCES-MIB and UCD-SNMP-MIB OIDs.
"""

from src.collectors.base import BaseCollector
from src.collectors.snmp_cli import SNMPCliMixin
from src.models.telemetry import RawTelemetry

SYSTEM_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
}

HOST_RESOURCE_OIDS = {
    "cpu_load_1min": "1.3.6.1.4.1.2021.10.1.3.1",
    "cpu_load_5min": "1.3.6.1.4.1.2021.10.1.3.2",
    "mem_total": "1.3.6.1.4.1.2021.4.5.0",
    "mem_avail": "1.3.6.1.4.1.2021.4.6.0",
    "cpu_idle": "1.3.6.1.4.1.2021.11.11.0",
    "disk_percent": "1.3.6.1.4.1.2021.9.1.9.1",
    "cpu_temp": "1.3.6.1.4.1.2021.13.16.1.3.1",
    "process_count": "1.3.6.1.2.1.25.1.6.0",
}


class SNMPEdgeCollector(SNMPCliMixin, BaseCollector):
    """Collects system metrics from the Raspberry Pi edge collector via SNMP."""

    def __init__(self, asset_id: str, host: str, community: str = "aevus_ro", poll_interval: int = 30):
        super().__init__(asset_id, host, poll_interval)
        self.community = community

    async def is_reachable(self) -> bool:
        value = await self._snmp_get(SYSTEM_OIDS["sys_descr"])
        return value is not None

    async def poll(self) -> list[RawTelemetry]:
        readings: list[RawTelemetry] = []

        # CPU usage (100 - idle)
        cpu_idle = await self._snmp_get(HOST_RESOURCE_OIDS["cpu_idle"])
        if cpu_idle is not None:
            try:
                usage = 100.0 - float(cpu_idle)
                readings.append(
                    self._make_reading(
                        metric="cpu_load",
                        value=round(usage, 1),
                        unit="%",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["cpu_idle"],
                        group="system",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("cpu_parse_error", raw=cpu_idle)

        # Load average 1min
        load1 = await self._snmp_get(HOST_RESOURCE_OIDS["cpu_load_1min"])
        if load1 is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="load_avg_1m",
                        value=float(load1),
                        unit="",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["cpu_load_1min"],
                        group="system",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("load_parse_error", raw=load1)

        # Load average 5min
        load5 = await self._snmp_get(HOST_RESOURCE_OIDS["cpu_load_5min"])
        if load5 is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="load_avg_5m",
                        value=float(load5),
                        unit="",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["cpu_load_5min"],
                        group="system",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("load5_parse_error", raw=load5)

        # Memory usage
        mem_total = await self._snmp_get(HOST_RESOURCE_OIDS["mem_total"])
        mem_avail = await self._snmp_get(HOST_RESOURCE_OIDS["mem_avail"])
        if mem_total and mem_avail:
            try:
                total = float(mem_total)
                avail = float(mem_avail)
                if total > 0:
                    pct = ((total - avail) / total) * 100
                    readings.append(
                        self._make_reading(
                            metric="memory_used",
                            value=round(pct, 1),
                            unit="%",
                            source="snmp",
                            group="system",
                        )
                    )
            except (ValueError, TypeError):
                self.log.debug("mem_parse_error", total=mem_total, avail=mem_avail)

        # Disk usage
        disk_pct = await self._snmp_get(HOST_RESOURCE_OIDS["disk_percent"])
        if disk_pct is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="disk_used",
                        value=float(disk_pct),
                        unit="%",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["disk_percent"],
                        group="system",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("disk_parse_error", raw=disk_pct)

        # CPU temperature (may not be available on all Pis)
        cpu_temp = await self._snmp_get(HOST_RESOURCE_OIDS["cpu_temp"])
        if cpu_temp is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="cpu_temp",
                        value=float(cpu_temp),
                        unit="°C",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["cpu_temp"],
                        group="environment",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("cpu_temp_parse_error", raw=cpu_temp)

        # Total processes
        proc_count = await self._snmp_get(HOST_RESOURCE_OIDS["process_count"])
        if proc_count is not None:
            try:
                readings.append(
                    self._make_reading(
                        metric="process_count",
                        value=float(proc_count),
                        unit="count",
                        source="snmp",
                        oid=HOST_RESOURCE_OIDS["process_count"],
                        group="system",
                    )
                )
            except (ValueError, TypeError):
                self.log.debug("proc_count_parse_error", raw=proc_count)

        # Uptime — handle multiple formats
        uptime_raw = await self._snmp_get(SYSTEM_OIDS["sys_uptime"])
        if uptime_raw is not None:
            try:
                if "(" in uptime_raw:
                    ticks = float(uptime_raw.split("(")[1].split(")")[0])
                else:
                    # Format like "0:0:09:33.30" — parse d:h:m:s
                    parts = uptime_raw.replace(" ", "").split(":")
                    if len(parts) >= 4:
                        days = float(parts[0])
                        hrs = float(parts[1])
                        mins = float(parts[2])
                        secs = float(parts[3])
                        ticks = (days * 86400 + hrs * 3600 + mins * 60 + secs) * 100
                    else:
                        ticks = float(uptime_raw)
                hours = ticks / 360000.0
                readings.append(
                    self._make_reading(
                        metric="uptime_hours",
                        value=round(hours, 2),
                        unit="hrs",
                        source="snmp",
                        oid=SYSTEM_OIDS["sys_uptime"],
                        group="system",
                    )
                )
            except (ValueError, IndexError, TypeError):
                self.log.debug("uptime_parse_error", raw=uptime_raw)

        return readings

    # SNMP CLI transport (_snmp_get / _snmp_get_sync) is provided by SNMPCliMixin.
