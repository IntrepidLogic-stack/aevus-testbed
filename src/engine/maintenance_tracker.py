"""
Aevus Testbed — Run-Hours / Maintenance-Due Tracker

Watches the equipment run-hours counter (e.g., SCADAPack 470 RunHours UInt32 at
Modbus register 40019) and emits a P3 'maintenance interval due' event each time
a configurable boundary is crossed (default every 500 operating hours).

Design notes:
- Pure-function check() — collectors hand in (asset_id, run_hours_value).
- First observation seeds baseline silently (no false alarm on initial discovery).
- Idempotent — the same boundary only fires once even if check() is called many
  times with values above it.
- Counter rollover/reset handling: if the new value is materially lower than the
  prior value, log it and re-seed the baseline (do NOT emit a maintenance event).
  Typical cause: RTU service swap, register reset after PM, UInt32 wrap (~490k
  years out, but documented for completeness).
- Multi-boundary jumps (rare — implies prolonged offline + catch-up read) emit
  ONE event referencing the highest boundary crossed, with the count in metadata.
- Configurable interval per asset class — pumps may want every 250h, gas
  compressors every 1000h. Default 500h per midstream-O&G norm.

Cross-references:
- AEVUS_ALARM_CATALOG_v1.md §5 A-P3-11 (Maintenance interval due)
- CLAUDE.md §"Equipment Fleet" — SCADAPack 470 register map
- IL-9000 interlock: this module does NOT initiate any actuation. It only
  announces 'time to send a credentialed tech.' src/il9000.py applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog

logger = structlog.get_logger()

DEFAULT_INTERVAL_HOURS = 500
ROLLOVER_TOLERANCE_HOURS = 24  # new < prior by >24h → treat as reset, re-seed


@dataclass(frozen=True)
class MaintenanceDue:
    """Event emitted when an asset crosses a maintenance-interval boundary."""

    asset_id: str
    asset_name: str
    run_hours: int  # current observed run-hours value
    boundary_crossed: int  # the multiple-of-interval most recently crossed
    boundaries_in_jump: int  # how many boundaries were skipped (usually 1)
    interval_hours: int  # the interval setting at the time of the event
    detected_at: datetime

    def to_message(self) -> str:
        if self.boundaries_in_jump == 1:
            return (
                f"{self.asset_name}: maintenance interval due at "
                f"{self.boundary_crossed} run-hours "
                f"(current {self.run_hours}h, every {self.interval_hours}h)"
            )
        return (
            f"{self.asset_name}: maintenance interval due — "
            f"{self.boundaries_in_jump} intervals crossed in one read "
            f"(latest boundary {self.boundary_crossed}h, current {self.run_hours}h, "
            f"every {self.interval_hours}h). Likely catch-up after offline gap."
        )


class _PersistBackend(Protocol):
    """Optional persistence — anything matching these two calls works
    (SQLite adapter, Redis, in-memory mock)."""

    def get_runhours_baseline(self, asset_id: str) -> int | None: ...
    def set_runhours_baseline(self, asset_id: str, run_hours: int) -> None: ...


class MaintenanceTracker:
    """Per-asset run-hours baseline + boundary crossing detection."""

    def __init__(
        self,
        interval_hours: int = DEFAULT_INTERVAL_HOURS,
        db: _PersistBackend | None = None,
    ) -> None:
        if interval_hours <= 0:
            raise ValueError(f"interval_hours must be positive (got {interval_hours})")
        self.interval_hours = interval_hours
        self._baseline: dict[str, int] = {}  # asset_id -> last-observed run-hours
        self._db = db
        self.log = logger.bind(component="maintenance_tracker", interval_h=interval_hours)

    def check(
        self,
        asset_id: str,
        asset_name: str,
        run_hours: int,
        interval_hours_override: int | None = None,
    ) -> MaintenanceDue | None:
        """Compare run_hours against last-known. Emit a MaintenanceDue event if
        any new interval-boundary has been crossed since the prior observation.

        Args:
            asset_id: e.g., "RTU-01"
            asset_name: human-readable, e.g., "SCADAPack 470"
            run_hours: integer hours value from the device (negative rejected).
            interval_hours_override: per-asset interval override; defaults to the
                tracker's configured interval.

        Returns:
            MaintenanceDue event on new boundary crossing, else None.
        """
        if run_hours < 0:
            self.log.warning(
                "runhours_negative_rejected", asset=asset_id, value=run_hours
            )
            return None

        interval = (
            interval_hours_override
            if interval_hours_override is not None
            else self.interval_hours
        )
        if interval <= 0:
            raise ValueError(f"interval_hours_override must be positive (got {interval})")

        prior = self._lookup(asset_id)

        if prior is None:
            # First observation — seed silently.
            self._store(asset_id, run_hours)
            self.log.info(
                "runhours_baseline_set", asset=asset_id, run_hours=run_hours
            )
            return None

        if run_hours + ROLLOVER_TOLERANCE_HOURS < prior:
            # Counter reset / rollover. Re-seed, do not alarm.
            self.log.warning(
                "runhours_reset_detected",
                asset=asset_id,
                prior=prior,
                new=run_hours,
                delta=run_hours - prior,
            )
            self._store(asset_id, run_hours)
            return None

        if run_hours <= prior:
            # Same or trivial backwards drift inside tolerance — no-op.
            return None

        # Compute how many interval boundaries lie strictly above prior and
        # at or below run_hours.
        # boundaries are k*interval for positive k.
        first_boundary_above_prior = (prior // interval + 1) * interval
        if first_boundary_above_prior > run_hours:
            # No boundary crossed this delta. Update baseline, no event.
            self._store(asset_id, run_hours)
            return None

        # At least one boundary crossed.
        last_boundary_at_or_below = (run_hours // interval) * interval
        boundaries_in_jump = (
            (last_boundary_at_or_below - first_boundary_above_prior) // interval + 1
        )

        self._store(asset_id, run_hours)
        event = MaintenanceDue(
            asset_id=asset_id,
            asset_name=asset_name,
            run_hours=run_hours,
            boundary_crossed=last_boundary_at_or_below,
            boundaries_in_jump=boundaries_in_jump,
            interval_hours=interval,
            detected_at=datetime.now(UTC),
        )
        self.log.warning(
            "maintenance_interval_due",
            asset=asset_id,
            boundary=last_boundary_at_or_below,
            run_hours=run_hours,
            boundaries_in_jump=boundaries_in_jump,
        )
        return event

    def baseline(self, asset_id: str) -> int | None:
        """Current baseline run-hours for an asset, if any."""
        return self._lookup(asset_id)

    def reset(self, asset_id: str) -> None:
        """Forget the recorded baseline (e.g., post-PM service done, counter
        intentionally zeroed by tech)."""
        self._baseline.pop(asset_id, None)
        if self._db is not None:
            self._db.set_runhours_baseline(asset_id, 0)
        self.log.info("runhours_baseline_reset", asset=asset_id)

    # ---- internal ----------------------------------------------------------

    def _lookup(self, asset_id: str) -> int | None:
        if asset_id in self._baseline:
            return self._baseline[asset_id]
        if self._db is not None:
            stored = self._db.get_runhours_baseline(asset_id)
            if stored is not None and stored > 0:
                self._baseline[asset_id] = stored
                return stored
        return None

    def _store(self, asset_id: str, run_hours: int) -> None:
        self._baseline[asset_id] = run_hours
        if self._db is not None:
            self._db.set_runhours_baseline(asset_id, run_hours)
