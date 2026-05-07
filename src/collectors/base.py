"""
Aevus Testbed — Base Collector Interface
All equipment collectors inherit from this.
"""

import abc
import structlog
from datetime import datetime, timezone

from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()


class BaseCollector(abc.ABC):
    """Abstract base for all device collectors."""

    def __init__(self, asset_id: str, host: str, poll_interval: int = 30):
        self.asset_id = asset_id
        self.host = host
        self.poll_interval = poll_interval
        self.last_poll: datetime | None = None
        self.consecutive_failures: int = 0
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
        return datetime.now(timezone.utc)

    def _make_reading(
        self,
        metric: str,
        value: float,
        unit: str,
        source: str = "snmp",
        oid: str | None = None,
        modbus_register: int | None = None,
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
        )

    async def safe_poll(self) -> list[RawTelemetry]:
        """Poll with error handling and failure tracking."""
        try:
            readings = await self.poll()
            self.last_poll = self._now()
            self.consecutive_failures = 0
            self.log.info("poll_success", readings=len(readings))
            return readings
        except Exception as e:
            self.consecutive_failures += 1
            self.log.error(
                "poll_failed",
                error=str(e),
                consecutive_failures=self.consecutive_failures,
            )
            return []
