"""
Aevus Testbed --- Alert Engine
Monitors normalized vitals against thresholds and generates alerts.

The engine is stateful: it tracks which alerts are currently open so it
can avoid duplicate firing and auto-resolve when conditions clear.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.models.alert import Alert

if TYPE_CHECKING:
    from src.models.telemetry import VitalSign

logger = structlog.get_logger()

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
        self.log = logger.bind(component="alert_engine")

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
