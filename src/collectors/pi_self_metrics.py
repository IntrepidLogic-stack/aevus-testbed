"""
Pi self-observability collector.

Reads local Linux/Raspberry Pi sensors so the edge collector reports
ON itself as a first-class asset. No SNMP, no network — all local
syscalls/files.

Metrics:
  - cpu_temp        : SoC temperature via vcgencmd (°C)
  - disk_used_pct   : root filesystem usage (%)
  - load_avg_5m     : 5-min load average (unitless)
  - failed_services : count of systemd units in failed state
  - mem_used_pct    : memory usage from /proc/meminfo (%)
  - uptime_hours    : system uptime from /proc/uptime
"""
from __future__ import annotations
import asyncio, subprocess, os
from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry


class PiSelfMetricsCollector(BaseCollector):
    expected_metrics = frozenset({"cpu_temp", "disk_used_pct", "load_avg_5m"})

    def __init__(self, asset_id="PI-01", poll_interval=15):
        super().__init__(asset_id, "127.0.0.1", poll_interval)

    async def is_reachable(self) -> bool:
        return True  # local always reachable

    async def safe_poll(self):
        try:
            self.last_poll = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            readings = await self.poll()
            self.consecutive_failures = 0
            return readings
        except Exception:
            self.consecutive_failures += 1
            return []

    async def poll(self):
        r = []

        # 1. CPU temperature via vcgencmd (Raspberry Pi specific)
        try:
            out = await asyncio.to_thread(
                subprocess.check_output, ["vcgencmd", "measure_temp"],
                text=True, timeout=2,
            )
            # format: "temp=47.7'C\n"
            t = float(out.split("=")[1].split("'")[0])
            r.append(self._make_reading(metric="cpu_temp", value=t, unit="°C", source="local"))
        except Exception:
            pass

        # 2. Disk usage on /
        try:
            out = await asyncio.to_thread(
                subprocess.check_output, ["df", "--output=pcent", "/"],
                text=True, timeout=2,
            )
            pct = int(out.splitlines()[1].strip().rstrip("%"))
            r.append(self._make_reading(metric="disk_used_pct", value=pct, unit="%", source="local"))
        except Exception:
            pass

        # 3. Load average (5-min)
        try:
            with open("/proc/loadavg") as f:
                load_5m = float(f.read().split()[1])
            r.append(self._make_reading(metric="load_avg_5m", value=round(load_5m, 2), unit="", source="local"))
        except Exception:
            pass

        # 4. Failed systemd services
        try:
            out = await asyncio.to_thread(
                subprocess.check_output, ["systemctl", "--failed", "--no-legend"],
                text=True, timeout=2,
            )
            failed = len([line for line in out.splitlines() if line.strip()])
            r.append(self._make_reading(metric="failed_services", value=failed, unit="count", source="local"))
        except Exception:
            pass

        # 5. Memory usage from /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                meminfo = {line.split(":")[0]: int(line.split(":")[1].strip().split()[0])
                          for line in f if line.split(":")[0] in ("MemTotal", "MemAvailable")}
            if "MemTotal" in meminfo and "MemAvailable" in meminfo:
                used_pct = (1 - meminfo["MemAvailable"] / meminfo["MemTotal"]) * 100
                r.append(self._make_reading(metric="mem_used_pct", value=round(used_pct, 1), unit="%", source="local"))
        except Exception:
            pass

        # 6. System uptime
        try:
            with open("/proc/uptime") as f:
                uptime_s = float(f.read().split()[0])
            r.append(self._make_reading(metric="uptime", value=round(uptime_s / 3600, 2), unit="hrs", source="local"))
        except Exception:
            pass

        return r
