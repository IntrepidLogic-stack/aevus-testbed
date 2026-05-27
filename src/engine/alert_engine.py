"""
Aevus Testbed --- Alert Engine
Monitors normalized vitals against thresholds and generates alerts.

The engine is stateful: it tracks which alerts are currently open so it
can avoid duplicate firing and auto-resolve when conditions clear.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import settings
from src.models.alert import Alert
from src.models.telemetry import VitalSign

# ──────────────────────────────────────────────────────────────────────────
# Trap-driven event handling (Phase 1 — Event-Driven Edge)
# ──────────────────────────────────────────────────────────────────────────
# Maps SNMP trap event names → (severity, alert_key, message_template,
# auto_resolve_key). auto_resolve_key, when non-None, names another
# alert key on the same asset that should auto-resolve when this event
# fires (e.g. linkUp resolves linkDown).
TRAP_EVENT_RULES: dict[str, dict[str, Any]] = {
    "coldStart": {
        "severity": "warning",
        "key": "COLD_START",
        "message": "{asset_name} reported a cold start (device rebooted)",
        "resolves": None,
    },
    "warmStart": {
        "severity": "warning",
        "key": "WARM_START",
        "message": "{asset_name} reported a warm start",
        "resolves": None,
    },
    "linkDown": {
        "severity": "critical",
        "key": "LINK_DOWN",
        "message": "{asset_name} interface link DOWN{if_clause}",
        "resolves": None,
    },
    "linkUp": {
        "severity": "info",  # used internally; we don't fire alerts for linkUp
        "key": "LINK_UP",
        "message": "{asset_name} interface link UP{if_clause}",
        "resolves": "LINK_DOWN",
    },
    "authenticationFailure": {
        "severity": "critical",
        "key": "AUTH_FAILURE",
        "message": "{asset_name} reported an SNMP authentication failure (possible intrusion attempt)",
        "resolves": None,
    },
    "egpNeighborLoss": {
        "severity": "warning",
        "key": "EGP_NEIGHBOR_LOSS",
        "message": "{asset_name} lost an EGP neighbor",
        "resolves": None,
    },
}

# Standard SNMP varbind OID for the ifIndex on link traps.
_IF_INDEX_OID = "1.3.6.1.2.1.2.2.1.1"


def _extract_if_index(varbinds: dict[str, Any]) -> int | None:
    """Pull the ifIndex value from a link trap's varbinds, if present.

    The standard linkDown / linkUp PDUs carry ifIndex as an additional
    varbind under either the bare OID or a per-instance suffix
    (e.g. 1.3.6.1.2.1.2.2.1.1.5 for ifIndex on interface 5). We accept
    either form.
    """
    for oid, value in varbinds.items():
        if oid == _IF_INDEX_OID or oid.startswith(_IF_INDEX_OID + "."):
            try:
                return int(value)
            except (ValueError, TypeError):
                # Sometimes the index is encoded in the OID suffix
                # itself; pull the last component.
                suffix = oid[len(_IF_INDEX_OID) + 1 :]
                if suffix.isdigit():
                    return int(suffix)
    return None


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
        missed_polls: int | None = None,
    ) -> Alert | None:
        """Generate (or resolve) a comms-loss alert based on staleness.

        An asset is considered offline once it has missed
        ``missed_polls`` consecutive poll intervals. When ``missed_polls``
        is None the value from settings is used.

        Returns a new or state-changed alert, or None.
        """
        if last_seen is None:
            return None

        threshold_misses = (
            missed_polls if missed_polls is not None else settings.missed_polls_offline
        )
        threshold_s = poll_interval * threshold_misses
        now = datetime.now(UTC)
        age = (now - last_seen).total_seconds()
        key = (asset_id, "OFFLINE")

        if age > threshold_s:
            existing = self._open_alerts.get(key)
            if existing is None:
                alert = Alert(
                    id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                    severity="critical",
                    asset_id=asset_id,
                    asset_name=asset_name,
                    message=(
                        f"{asset_name} comms loss — no response for {int(age)}s "
                        f"({threshold_misses}× poll interval)"
                    ),
                    detected_at=now,
                    status="open",
                )
                self._open_alerts[key] = alert
                self.log.warning(
                    "asset_offline",
                    asset=asset_id,
                    age_s=int(age),
                    threshold_s=threshold_s,
                )
                return alert
            # Already open — nothing new to emit.
            return None

        if key in self._open_alerts:
            # Asset is back within threshold — auto-resolve.
            existing = self._open_alerts[key]
            existing.status = "resolved"
            existing.resolved_at = now
            del self._open_alerts[key]
            self.log.info("asset_back_online", asset=asset_id)
            return existing

        return None

    def evaluate_partial(
        self,
        asset_id: str,
        asset_name: str,
        missing_metrics: set[str],
    ) -> Alert | None:
        """Fire / resolve a PARTIAL_TELEMETRY alert.

        Called by the scheduler after a *successful* poll when the
        returned reading set is missing one or more of the collector's
        ``expected_metrics``. This catches the failure mode where the
        device is reachable (sysDescr / TCP handshake works) but some
        sensor channel or OID has gone dark — invisible to the comms-loss
        check, which only triggers on a fully empty poll.

        Returns the new or state-changed alert, or None.
        """
        key = (asset_id, "PARTIAL_TELEMETRY")
        now = datetime.now(UTC)

        if missing_metrics:
            existing = self._open_alerts.get(key)
            preview = ", ".join(sorted(missing_metrics)[:5])
            if len(missing_metrics) > 5:
                preview += f", +{len(missing_metrics) - 5} more"

            if existing is None:
                alert = Alert(
                    id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                    severity="warning",
                    asset_id=asset_id,
                    asset_name=asset_name,
                    message=(
                        f"{asset_name} partial telemetry — "
                        f"{len(missing_metrics)} metric(s) missing: {preview}"
                    ),
                    detected_at=now,
                    status="open",
                )
                self._open_alerts[key] = alert
                self.log.warning(
                    "asset_partial_telemetry",
                    asset=asset_id,
                    missing_count=len(missing_metrics),
                    missing=sorted(missing_metrics),
                )
                return alert
            # Already open — refresh the missing-list in the message so the
            # operator always sees the current gap, but don't re-emit.
            existing.message = (
                f"{asset_name} partial telemetry — "
                f"{len(missing_metrics)} metric(s) missing: {preview}"
            )
            return None

        # No missing metrics — resolve if previously open.
        if key in self._open_alerts:
            existing = self._open_alerts[key]
            existing.status = "resolved"
            existing.resolved_at = now
            del self._open_alerts[key]
            self.log.info("asset_telemetry_restored", asset=asset_id)
            return existing

        return None

    def evaluate_event(
        self,
        asset_id: str,
        asset_name: str,
        event_type: str,
        varbinds: dict[str, Any] | None = None,
    ) -> list[Alert]:
        """Consume a trap-driven event and emit alert state changes.

        Called by the scheduler's trap consumer for every TrapEvent that
        comes off the receiver queue. Returns a list of new or
        state-changed alerts to persist and broadcast — empty if the
        event was informational only.

        Behaviors:
          • Maps known trap event_types (linkDown, coldStart, etc.) to
            alerts via TRAP_EVENT_RULES.
          • linkUp auto-resolves any open LINK_DOWN on the same asset.
          • ANY trap from a previously-OFFLINE asset auto-resolves the
            OFFLINE alert (proof-of-life — the device clearly responded).
          • Unknown trap OIDs are logged but do not raise; we'd rather
            see noise than drop events.

        Args:
            asset_id: Resolved asset ID (caller is responsible for
                IP→asset mapping; if no asset matches, caller should skip).
            asset_name: Human-readable name for alert messages.
            event_type: Friendly trap name from SNMP_TRAP_OIDS, OR a raw
                OID string for vendor-specific traps.
            varbinds: Optional dict of OID → value from the PDU. Used to
                enrich messages (e.g. ifIndex on link traps).

        Returns:
            List of alerts to persist + broadcast.
        """
        varbinds = varbinds or {}
        now = datetime.now(UTC)
        changes: list[Alert] = []

        # ─── Proof-of-life: any trap auto-resolves the OFFLINE alert ─────
        offline_key = (asset_id, "OFFLINE")
        if offline_key in self._open_alerts:
            existing = self._open_alerts[offline_key]
            existing.status = "resolved"
            existing.resolved_at = now
            del self._open_alerts[offline_key]
            self.log.info(
                "asset_back_online_via_trap",
                asset=asset_id,
                trigger=event_type,
            )
            changes.append(existing)

        # ─── Known trap → alert mapping ───────────────────────────────────
        rule = TRAP_EVENT_RULES.get(event_type)
        if rule is None:
            # Vendor-specific or unknown OID. Log and emit a generic
            # informational alert so it shows up in the audit trail but
            # doesn't page anyone.
            self.log.info(
                "trap_unknown_oid",
                asset=asset_id,
                event_type=event_type,
                varbinds=list(varbinds),
            )
            return changes

        # Build a friendly message. Include ifIndex on link traps when
        # present so operators can identify the affected port.
        if_clause = ""
        if rule["key"] in ("LINK_DOWN", "LINK_UP"):
            if_index = _extract_if_index(varbinds)
            if if_index is not None:
                if_clause = f" (ifIndex {if_index})"

        message = rule["message"].format(asset_name=asset_name, if_clause=if_clause)

        # Auto-resolve a paired alert if the rule says so (linkUp → linkDown).
        if rule["resolves"]:
            paired_key = (asset_id, rule["resolves"])
            paired = self._open_alerts.get(paired_key)
            if paired is not None:
                paired.status = "resolved"
                paired.resolved_at = now
                del self._open_alerts[paired_key]
                self.log.info(
                    "alert_resolved_by_trap",
                    alert_id=paired.id,
                    asset=asset_id,
                    resolved_by=event_type,
                )
                changes.append(paired)

        # linkUp is purely informational — we resolved the linkDown above,
        # we don't need to fire a separate "link is up" alert.
        if event_type == "linkUp":
            return changes

        # Fire or update the alert.
        key = (asset_id, rule["key"])
        existing = self._open_alerts.get(key)

        if existing is None:
            alert = Alert(
                id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                severity=rule["severity"],
                asset_id=asset_id,
                asset_name=asset_name,
                message=message,
                detected_at=now,
                status="open",
            )
            self._open_alerts[key] = alert
            self.log.warning(
                "alert_fired_from_trap",
                alert_id=alert.id,
                asset=asset_id,
                event_type=event_type,
                severity=rule["severity"],
            )
            changes.append(alert)
        else:
            # Re-firing of a still-open trap (e.g. linkDown reasserted).
            # Refresh the timestamp + message but don't emit a duplicate.
            existing.message = message
            existing.detected_at = now

        return changes

    def evaluate_reachability(
        self,
        asset_id: str,
        asset_name: str,
        state: str,
        loss_pct: float = 0.0,
        avg_rtt_ms: float | None = None,
        consecutive_failures: int = 0,
    ) -> list[Alert]:
        """Consume an ICMP reachability state transition.

        Kept distinct from OFFLINE comms-loss because the two signals
        answer different questions:
          • OFFLINE   = "application layer hasn't responded in N polls"
          • UNREACHABLE / REACHABILITY_DEGRADED = "L3 ping says path or device is broken"

        Both can be open at once. Operators want to see the difference
        between "device is gone" and "SNMP agent died but the box is up".

        Args:
            state: 'up' | 'degraded' | 'down' (from ReachabilityEvent.state).

        Returns:
            List of new or state-changed alerts.
        """
        now = datetime.now(UTC)
        changes: list[Alert] = []

        down_key = (asset_id, "UNREACHABLE")
        degraded_key = (asset_id, "REACHABILITY_DEGRADED")

        def _resolve(key: tuple[str, str]) -> None:
            existing = self._open_alerts.get(key)
            if existing is not None:
                existing.status = "resolved"
                existing.resolved_at = now
                del self._open_alerts[key]
                self.log.info(
                    "reachability_alert_resolved",
                    alert_id=existing.id,
                    asset=asset_id,
                    key=key[1],
                )
                changes.append(existing)

        if state == "up":
            # Both alerts auto-resolve. ICMP-up is also proof of life,
            # so resolve OFFLINE too (same logic as evaluate_event).
            _resolve(down_key)
            _resolve(degraded_key)
            _resolve((asset_id, "OFFLINE"))
            return changes

        if state == "down":
            # Resolve degraded if escalating from degraded → down (since
            # the same condition is now expressed by the more severe alert).
            _resolve(degraded_key)
            if down_key not in self._open_alerts:
                alert = Alert(
                    id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                    severity="critical",
                    asset_id=asset_id,
                    asset_name=asset_name,
                    message=(
                        f"{asset_name} UNREACHABLE — ICMP probe failed "
                        f"{consecutive_failures} consecutive times"
                    ),
                    detected_at=now,
                    status="open",
                )
                self._open_alerts[down_key] = alert
                self.log.warning(
                    "asset_unreachable",
                    alert_id=alert.id,
                    asset=asset_id,
                    consecutive_failures=consecutive_failures,
                )
                changes.append(alert)
            return changes

        if state == "degraded":
            # If we're already in down, don't downgrade by firing degraded.
            if down_key in self._open_alerts:
                return changes
            if degraded_key not in self._open_alerts:
                alert = Alert(
                    id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
                    severity="warning",
                    asset_id=asset_id,
                    asset_name=asset_name,
                    message=(
                        f"{asset_name} reachability degraded — "
                        f"{loss_pct:.1f}% packet loss"
                        + (f", avg RTT {avg_rtt_ms:.1f}ms" if avg_rtt_ms else "")
                    ),
                    detected_at=now,
                    status="open",
                )
                self._open_alerts[degraded_key] = alert
                self.log.warning(
                    "asset_reachability_degraded",
                    alert_id=alert.id,
                    asset=asset_id,
                    loss_pct=loss_pct,
                )
                changes.append(alert)
            return changes

        # Unknown / 'unknown' state — no-op.
        return changes

    def acknowledge(self, alert_id: str) -> Alert | None:
        """Acknowledge an open alert by ID."""
        for _key, alert in self._open_alerts.items():
            if alert.id == alert_id and alert.status == "open":
                alert.status = "acknowledged"
                alert.acknowledged_at = datetime.now(UTC)
                self.log.info("alert_acknowledged", alert_id=alert_id)
                return alert
        return None

    @staticmethod
    def _build_message(asset_name: str, vital: VitalSign) -> str:
        """Build a human-readable alert message."""
        if vital.status == "bad":
            return f"{asset_name}: {vital.label} critical at {vital.value}"
        return f"{asset_name}: {vital.label} warning at {vital.value}"
