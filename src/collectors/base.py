"""
Aevus Testbed — Base Collector Interface
All equipment collectors inherit from this.
"""

import abc
import re
import time
from datetime import UTC, datetime

import structlog

from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()

# Matches the "Version <token>" field in a device sysDescr banner, capturing
# up to the next comma. Cisco IOS sysDescr looks like:
#   "Cisco IOS Software, C2960 Software (...), Version 15.0(2)SE11, RELEASE ..."
# so the captured group is "15.0(2)SE11".
_FIRMWARE_VERSION_RE = re.compile(r"Version ([^,]+)")


class BaseCollector(abc.ABC):
    """Abstract base for all device collectors."""

    def __init__(self, asset_id: str, host: str, poll_interval: int = 30):
        self.asset_id = asset_id
        self.host = host
        self.poll_interval = poll_interval
        self.last_poll: datetime | None = None
        self.consecutive_failures: int = 0
        self.poll_count: int = 0
        self.poll_success_count: int = 0
        self.last_poll_duration_ms: float = 0.0
        # Most-recent firmware/OS version string from device (e.g. sysDescr).
        # Populated by concrete collectors. The scheduler hands this to
        # FirmwareTracker each cycle to detect out-of-band changes.
        self.firmware_version: str | None = None
        self.log = logger.bind(collector=self.__class__.__name__, asset_id=asset_id, host=host)

    @abc.abstractmethod
    async def poll(self) -> list[RawTelemetry]:
        """Poll the device and return a list of raw telemetry readings.

        Returns an empty list if the device is unreachable.
        """
        ...

    @abc.abstractmethod
    async def is_reachable(self) -> bool:
        """Check if the device responds to a basic connectivity test."""
        ...

    def _now(self) -> datetime:
        """Return current UTC timestamp."""
        return datetime.now(UTC)

    @staticmethod
    def _parse_firmware_version(sys_descr: str | None) -> str | None:
        """Extract a clean firmware/OS version token from a device sysDescr.

        Cisco IOS reports its version as a long banner ending in
        "..., Version 15.0(2)SE11, RELEASE SOFTWARE ... Copyright (c) ...".
        We want just the version token ("15.0(2)SE11"), not the whole blob.

        Falls back to the stripped raw value when no "Version <x>" token is
        present (e.g. MikroTik RouterOS sysDescr, which carries no such field).
        Returns None for empty input.
        """
        if not sys_descr:
            return None
        cleaned = sys_descr.replace("STRING: ", "").strip().strip('"')
        match = _FIRMWARE_VERSION_RE.search(cleaned)
        if match:
            return match.group(1).strip()
        return cleaned or None

    def _make_reading(
        self,
        metric: str,
        value: float,
        unit: str,
        source: str = "snmp",
        oid: str | None = None,
        modbus_register: int | None = None,
        opcua_node: str | None = None,
        group: str = "",
    ) -> RawTelemetry:
        """Helper to create a RawTelemetry object."""
        return RawTelemetry(
            asset_id=self.asset_id,
            metric=metric,
            value=value,
            unit=unit,
            timestamp=self._now(),
            source=source,
            oid=oid,
            modbus_register=modbus_register,
            opcua_node=opcua_node,
            group=group,
        )

    async def safe_poll(self) -> list[RawTelemetry]:
        """Poll with error handling, failure tracking, and duration measurement."""
        self.poll_count += 1
        start = time.monotonic()
        try:
            readings = await self.poll()
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self.last_poll_duration_ms = elapsed_ms
            self.last_poll = self._now()
            self.consecutive_failures = 0
            self.poll_success_count += 1
            self.log.info("poll_success", readings=len(readings), duration_ms=round(elapsed_ms, 1))
            return readings
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self.last_poll_duration_ms = elapsed_ms
            self.consecutive_failures += 1
            self.log.error(
                "poll_failed",
                error=str(e),
                consecutive_failures=self.consecutive_failures,
                duration_ms=round(elapsed_ms, 1),
            )
            return []
