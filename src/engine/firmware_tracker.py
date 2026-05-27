"""
Aevus Testbed — Firmware Version Diff Tracker

Tracks the last-known firmware/OS version per asset and emits a P4 change event
when the version differs from prior poll. Out-of-band firmware changes are a
cyber/compliance signal (see AEVUS_ALARM_CATALOG_v1.md §8, C-04) — they should
never happen without an operator-initiated workflow.

Pure-function design: collectors hand in (asset_id, version_string) and receive
either None (no change / first poll) or a FirmwareChange event for the
AlertEngine to consume via evaluate_event().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class FirmwareChange:
    """Event emitted when an asset's firmware version differs from prior poll."""

    asset_id: str
    asset_name: str
    old_version: str
    new_version: str
    detected_at: datetime

    def to_message(self) -> str:
        return (
            f"{self.asset_name}: firmware version changed "
            f"{self.old_version!r} → {self.new_version!r} "
            f"(out-of-band change — investigate)"
        )


class _PersistBackend(Protocol):
    """Optional persistence — anything with these two methods works
    (a SQLite-backed adapter, a Redis adapter, an in-memory mock, etc.)."""

    def get_firmware_version(self, asset_id: str) -> str | None: ...
    def set_firmware_version(self, asset_id: str, version: str) -> None: ...


class FirmwareTracker:
    """Track last-known firmware version per asset, emit change events."""

    def __init__(self, db: _PersistBackend | None = None) -> None:
        # In-memory cache. If db is provided, the cache is loaded lazily
        # and writes flush through to persistent storage.
        self._versions: dict[str, str] = {}
        self._db = db
        self.log = logger.bind(component="firmware_tracker")

    def check(
        self,
        asset_id: str,
        asset_name: str,
        version: str,
    ) -> FirmwareChange | None:
        """Compare version against last-known. Return FirmwareChange on mismatch,
        else None. First-time observation is silent (no alarm on initial discovery).

        Empty / whitespace-only versions are treated as "unknown" and never
        produce a change event in either direction — prevents false alarms when
        a device temporarily returns garbage on its sysDescr OID.
        """
        normalized = (version or "").strip()
        if not normalized:
            return None

        prior = self._lookup(asset_id)
        if prior is None:
            # First observation — seed and stay silent.
            self._store(asset_id, normalized)
            self.log.info("firmware_baseline_set", asset=asset_id, version=normalized)
            return None

        if prior == normalized:
            return None

        # Real change — record + emit
        self._store(asset_id, normalized)
        event = FirmwareChange(
            asset_id=asset_id,
            asset_name=asset_name,
            old_version=prior,
            new_version=normalized,
            detected_at=datetime.now(UTC),
        )
        self.log.warning(
            "firmware_version_changed",
            asset=asset_id,
            old=prior,
            new=normalized,
        )
        return event

    def baseline(self, asset_id: str) -> str | None:
        """Return the current baseline version for an asset, if any."""
        return self._lookup(asset_id)

    def reset(self, asset_id: str) -> None:
        """Clear the recorded baseline for an asset (e.g., after planned upgrade)."""
        self._versions.pop(asset_id, None)
        if self._db is not None:
            self._db.set_firmware_version(asset_id, "")
        self.log.info("firmware_baseline_reset", asset=asset_id)

    # ---- internal ----------------------------------------------------------

    def _lookup(self, asset_id: str) -> str | None:
        if asset_id in self._versions:
            return self._versions[asset_id] or None
        if self._db is not None:
            stored = self._db.get_firmware_version(asset_id)
            if stored:
                self._versions[asset_id] = stored
                return stored
        return None

    def _store(self, asset_id: str, version: str) -> None:
        self._versions[asset_id] = version
        if self._db is not None:
            self._db.set_firmware_version(asset_id, version)
