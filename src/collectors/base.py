"""
Aevus Testbed — Base Collector Interface
All equipment collectors inherit from this.
"""

import abc
import typing
from datetime import UTC, datetime
from typing import ClassVar

import structlog

from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()


class BaseCollector(abc.ABC):
    """Abstract base for all device collectors.

    Subclass contract:

    * Implement ``poll()`` — returns a list of ``RawTelemetry``. Raise on
      hard failures (connection refused, timeout). The base class's
      ``safe_poll()`` will catch the exception and return ``[]``, which
      the scheduler interprets as a missed poll and feeds into the
      comms-loss alarm path.

    * Implement ``is_reachable()`` — a cheap liveness probe used by tools
      and tests. Should not raise.

    * Declare ``expected_metrics`` — the set of metric names this collector
      is *expected* to emit on every healthy poll. The scheduler compares
      this set against actual readings to detect partial-telemetry faults
      (e.g. a sensor channel dropping while the device is otherwise up).
      Leave empty only for collectors with intrinsically dynamic metric
      sets (such as per-interface counters).

    * Do NOT override ``safe_poll()``. It is the integration point with
      the scheduler's failure-handling and alarm pipeline. Marked
      ``@typing.final``.
    """

    #: Metric names this collector promises to emit when the device is
    #: healthy. Used by the scheduler to detect PARTIAL TELEMETRY faults.
    expected_metrics: ClassVar[frozenset[str]] = frozenset()

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
        return datetime.now(UTC)

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

    @typing.final
    async def safe_poll(self) -> list[RawTelemetry]:
        """Poll with error handling and failure tracking.

        This is the scheduler's integration point. **Do not override.**
        A failed poll returns ``[]`` (never raises) so the scheduler can
        feed staleness into the comms-loss alarm path. Subclasses should
        implement ``poll()`` and let exceptions propagate to here.
        """
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
