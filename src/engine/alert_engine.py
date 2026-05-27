"""
Aevus Testbed --- Alert Engine
Monitors normalized vitals against thresholds and generates alerts.

The engine is stateful: it tracks which alerts are currently open so it
can avoid duplicate firing and auto-resolve when conditions clear.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from src.models.alert import Alert

if TYPE_CHECKING:
    from src.models.telemetry import VitalSign

logger = structlog.get_logger()

# ISA-18.2 §7.5 chattering detection
CHATTER_WINDOW_S = 600  # 10-minute rolling window
CHATTER_THRESHOLD = 5  # fires within window → chattering
CHATTER_SHELF_S = 1800  # 30-minute auto-shelf after chattering meta-alarm

# Metrics that should generate alerts when status is warn or bad
ALERTABLE_METRICS = {
    # Radio
    "RSSI",
    "SNR",
    "TEMPERATURE",
    # RTU
    "SUCTION PRESSURE",
    "DISCHARGE PRESSURE",
    "BATTERY",
    "VIBRATION",
    "HIGH PRESSURE ALARM",
    "LOW BATTERY ALARM",
    "COMM FAULT",
    # Network
    "CPU LOAD",
    "RX ERRORS",
    "TX ERRORS",
}


class AlertEngine:
    """Stateful alert engine that tracks open alerts per asset+metric."""

    def __init__(self) -> None:
        # Key: (asset_id, metric_label) -> Alert
        self._open_alerts: dict[tuple[str, str], Alert] = {}
        # Chattering detection: per-key fire timestamps (rolling window)
        self._fire_history: dict[tuple[str, str], deque[datetime]] = {}
        # Auto-shelf expiry per key (ISA-18.2 §11) — set by chattering or manual shelve
        self._shelved_until: dict[tuple[str, str], datetime] = {}
        self.log = logger.bind(component="alert_engine")

    def is_shelved(self, asset_id: str, metric_label: str) -> bool:
        """Return True if (asset_id, metric_label) is currently shelved."""
        key = (asset_id, metric_label)
        expiry = self._shelved_until.get(key)
        if expiry is None:
            return False
        if datetime.now(UTC) >= expiry:
            # Shelf expired — auto-clear
            del self._shelved_until[key]
            self.log.info("alert_unshelved_auto", asset=asset_id, metric=metric_label)
            return False
        return True

    def shelve(
        self,
        asset_id: str,
        metric_label: str,
        duration_s: int = CHATTER_SHELF_S,
        reason: str = "manual",
    ) -> datetime:
        """Shelve an (asset_id, metric_label) for duration_s seconds.

        While shelved, the AlertEngine will not fire new alerts for this key.
        Existing open alerts are NOT auto-resolved — operator must act on them.
        Returns the shelf expiry timestamp.
        """
        expiry = datetime.now(UTC) + timedelta(seconds=duration_s)
        key = (asset_id, metric_label)
        self._shelved_until[key] = expiry
        self.log.warning(
            "alert_shelved",
            asset=asset_id,
            metric=metric_label,
            duration_s=duration_s,
            reason=reason,
            expires_at=expiry.isoformat(),
        )
        return expiry

    def _record_fire_and_check_chattering(
        self,
        asset_id: str,
        asset_name: str,
        metric_label: str,
        now: datetime,
    ) -> Alert | None:
        """Append a fire timestamp; if rate exceeds threshold, emit a CHATTERING
        meta-alarm and auto-shelve the underlying key for CHATTER_SHELF_S seconds.

        Returns the meta-alarm if one was generated, else None.
        """
        key = (asset_id, metric_label)
        hist = self._fire_history.setdefault(key, deque())
        hist.append(now)

        # Prune outside-window entries
        cutoff = now - timedelta(seconds=CHATTER_WINDOW_S)
        while hist and hist[0] < cutoff:
            hist.popleft()

        if len(hist) <= CHATTER_THRESHOLD:
            return None

        # Threshold crossed — emit meta-alarm + auto-shelve
        meta_key = (asset_id, f"CHATTERING:{metric_label}")
        if meta_key in self._open_alerts:
            return None  # already firing, do not double-emit

        meta = Alert(
            id=f"CHAT-{uuid.uuid4().hex[:8].upper()}",
            severity="warning",
            asset_id=asset_id,
            asset_name=asset_name,
            message=(
                f"{asset_name}: {metric_label} chattering "
                f"({len(hist)} fires in {CHATTER_WINDOW_S // 60} min) — "
                f"auto-shelved for {CHATTER_SHELF_S // 60} min (ISA-18.2 §7.5)"
            ),
            detected_at=now,
            status="open",
        )
        self._open_alerts[meta_key] = meta
        self.shelve(asset_id, metric_label, duration_s=CHATTER_SHELF_S, reason="chattering")
        self.log.warning(
            "alert_chattering",
            asset=asset_id,
            metric=metric_label,
            fires_in_window=len(hist),
            window_s=CHATTER_WINDOW_S,
        )
        return meta

    @property
    def open_alerts(self) -> list[Alert]:
        """Return all currently open alerts."""
        return list(self._open_alerts.values())

    def evaluate(
        self,
        asset_id: str,
        asset_name: str,
        vitals: list[VitalSign],
    ) -> list[Alert]:
        """Evaluate vitals and return newly generated or resolved alerts.

        Args:
            asset_id: The asset being checked.
            asset_name: Human-readable name for alert messages.
            vitals: Current normalized vitals for the asset.

        Returns:
            List of new or state-changed alerts from this evaluation.
        """
        changes: list[Alert] = []
        now = datetime.now(UTC)

        # Track which (asset_id, label) pairs we see this cycle
        seen_keys: set[tuple[str, str]] = set()

        for vital in vitals:
            if vital.label not in ALERTABLE_METRICS:
                continue
            if vital.status not in ("warn", "bad", "good"):
                continue

            key = (asset_id, vital.label)
            seen_keys.add(key)

            # ISA-18.2 §11 — skip evaluation if shelved (manual or auto-chattering)
            if self.is_shelved(asset_id, vital.label):
                continue

            existing = self._open_alerts.get(key)

            if vital.status in ("warn", "bad"):
                severity = "critical" if vital.status == "bad" else "warning"
                message = self._build_message(asset_name, vital)

                if existing is None:
                    # New alert
                    alert = Alert(
                        id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                        severity=severity,
                        asset_id=asset_id,
                        asset_name=asset_name,
                        message=message,
                        detected_at=now,
                        status="open",
                    )
                    self._open_alerts[key] = alert
                    changes.append(alert)
                    self.log.warning(
                        "alert_fired",
                        alert_id=alert.id,
                        asset=asset_id,
                        metric=vital.label,
                        severity=severity,
                    )
                    # ISA-18.2 §7.5 — track fire rate, emit meta-alarm if chattering
                    meta = self._record_fire_and_check_chattering(
                        asset_id, asset_name, vital.label, now
                    )
                    if meta is not None:
                        changes.append(meta)
                elif existing.severity != severity:
                    # Severity escalation/de-escalation
                    existing.severity = severity
                    existing.message = message
                    changes.append(existing)
                    self.log.info(
                        "alert_severity_changed",
                        alert_id=existing.id,
                        asset=asset_id,
                        metric=vital.label,
                        new_severity=severity,
                    )

            elif vital.status == "good" and existing is not None:
                # Condition cleared -- auto-resolve
                existing.status = "resolved"
                existing.resolved_at = now
                changes.append(existing)
                del self._open_alerts[key]
                self.log.info(
                    "alert_resolved",
                    alert_id=existing.id,
                    asset=asset_id,
                    metric=vital.label,
                )

        return changes

    def evaluate_offline(
        self,
        asset_id: str,
        asset_name: str,
        last_seen: datetime | None,
        poll_interval: int = 30,
    ) -> Alert | None:
        """Generate an alert if an asset hasn't been seen recently.

        Returns a new alert or None.
        """
        if last_seen is None:
            return None

        age = (datetime.now(UTC) - last_seen).total_seconds()
        key = (asset_id, "OFFLINE")

        if age > poll_interval * 5:
            existing = self._open_alerts.get(key)
            if existing is None:
                alert = Alert(
                    id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                    severity="critical",
                    asset_id=asset_id,
                    asset_name=asset_name,
                    message=f"{asset_name} has not responded for {int(age)}s",
                    detected_at=datetime.now(UTC),
                    status="open",
                )
                self._open_alerts[key] = alert
                self.log.warning("asset_offline", asset=asset_id, age_s=int(age))
                return alert
        elif key in self._open_alerts:
            # Asset is back
            existing = self._open_alerts[key]
            existing.status = "resolved"
            existing.resolved_at = datetime.now(UTC)
            del self._open_alerts[key]
            self.log.info("asset_back_online", asset=asset_id)
            return existing

        return None

    def record_event(
        self,
        asset_id: str,
        asset_name: str,
        event_type: str,
        message: str,
        severity: str = "info",
    ) -> Alert | None:
        """Record a point-in-time event alarm (firmware change, maintenance due,
        SNMP trap, etc.). Unlike threshold alarms, events don't auto-resolve —
        the operator acks/resolves them explicitly.

        Honors shelving via is_shelved() on the (asset_id, event_type) key.
        Deduplicates: if an OPEN event of the same (asset_id, event_type) already
        exists, the call is a no-op and returns None.

        Returns the new Alert if one was created, else None.
        """
        if self.is_shelved(asset_id, event_type):
            return None

        key = (asset_id, event_type)
        existing = self._open_alerts.get(key)
        if existing is not None and existing.status == "open":
            return None

        alert = Alert(
            id=f"EVT-{uuid.uuid4().hex[:8].upper()}",
            severity=severity,  # type: ignore[arg-type]
            asset_id=asset_id,
            asset_name=asset_name,
            message=message,
            detected_at=datetime.now(UTC),
            status="open",
        )
        self._open_alerts[key] = alert
        self.log.warning(
            "event_recorded",
            alert_id=alert.id,
            asset=asset_id,
            event_type=event_type,
            severity=severity,
        )
        return alert

    def acknowledge(self, alert_id: str, db=None) -> Alert | None:
        """Acknowledge an open alert by ID.

        Checks in-memory alerts first, then falls back to SQLite
        so alerts survive service restarts.
        """
        # Check in-memory first
        for _key, alert in self._open_alerts.items():
            if alert.id == alert_id and alert.status == "open":
                alert.status = "acknowledged"
                alert.acknowledged_at = datetime.now(UTC)
                self.log.info("alert_acknowledged", alert_id=alert_id)
                return alert

        # Fallback: check persistent storage
        if db is not None:
            alert = db.get_alert(alert_id)
            if alert is not None and alert.status == "open":
                alert.status = "acknowledged"
                alert.acknowledged_at = datetime.now(UTC)
                self.log.info("alert_acknowledged", alert_id=alert_id, source="sqlite")
                return alert

        return None

    def resolve(self, alert_id: str, db=None) -> "Alert | None":
        """Resolve an open or acknowledged alert by ID."""
        # Check in-memory first
        for _key, alert in self._open_alerts.items():
            if alert.id == alert_id and alert.status in ("open", "acknowledged"):
                alert.status = "resolved"
                alert.resolved_at = datetime.now(UTC)
                self.log.info("alert_resolved", alert_id=alert_id)
                return alert

        # Fallback: check persistent storage
        if db is not None:
            alert = db.get_alert(alert_id)
            if alert is not None and alert.status in ("open", "acknowledged"):
                alert.status = "resolved"
                alert.resolved_at = datetime.now(UTC)
                self.log.info("alert_resolved", alert_id=alert_id, source="sqlite")
                return alert

        return None

    @staticmethod
    def _build_message(asset_name: str, vital: VitalSign) -> str:
        """Build a human-readable alert message."""
        if vital.status == "bad":
            return f"{asset_name}: {vital.label} critical at {vital.value}"
        return f"{asset_name}: {vital.label} warning at {vital.value}"
