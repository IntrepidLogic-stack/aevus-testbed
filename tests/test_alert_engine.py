"""Tests for the stateful alert engine."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.engine.alert_engine import ALERTABLE_METRICS, AlertEngine
from src.models.telemetry import VitalSign


def _vital(label: str, value: str, raw: float, status: str) -> VitalSign:
    return VitalSign(label=label, value=value, raw_value=raw, unit="", status=status)


class TestAlertEngineEvaluate:
    """Tests for AlertEngine.evaluate()."""

    def test_no_alerts_when_all_good(self):
        engine = AlertEngine()
        vitals = [_vital("RSSI", "-65 dBm", -65.0, "good")]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert changes == []
        assert len(engine.open_alerts) == 0

    def test_fires_warning_alert(self):
        engine = AlertEngine()
        vitals = [_vital("RSSI", "-85 dBm", -85.0, "warn")]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert len(changes) == 1
        assert changes[0].severity == "warning"
        assert changes[0].status == "open"
        assert changes[0].asset_id == "RAD-01"

    def test_fires_critical_alert(self):
        engine = AlertEngine()
        vitals = [_vital("RSSI", "-95 dBm", -95.0, "bad")]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert len(changes) == 1
        assert changes[0].severity == "critical"

    def test_no_duplicate_alerts(self):
        """Same condition on second eval should not fire again."""
        engine = AlertEngine()
        vitals = [_vital("RSSI", "-85 dBm", -85.0, "warn")]
        engine.evaluate("RAD-01", "Trio #1", vitals)
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert changes == []
        assert len(engine.open_alerts) == 1

    def test_auto_resolve(self):
        """Alert resolves when condition clears."""
        engine = AlertEngine()
        # Fire
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        assert len(engine.open_alerts) == 1
        # Resolve
        changes = engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-65 dBm", -65.0, "good")])
        assert len(changes) == 1
        assert changes[0].status == "resolved"
        assert changes[0].resolved_at is not None
        assert len(engine.open_alerts) == 0

    def test_severity_escalation(self):
        """Alert escalates from warning to critical."""
        engine = AlertEngine()
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        changes = engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-95 dBm", -95.0, "bad")])
        assert len(changes) == 1
        assert changes[0].severity == "critical"

    def test_severity_deescalation(self):
        """Alert de-escalates from critical to warning."""
        engine = AlertEngine()
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-95 dBm", -95.0, "bad")])
        changes = engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        assert len(changes) == 1
        assert changes[0].severity == "warning"

    def test_non_alertable_metric_ignored(self):
        """Metrics not in ALERTABLE_METRICS don't generate alerts."""
        engine = AlertEngine()
        vitals = [_vital("TX POWER", "20 dBm", 20.0, "warn")]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert changes == []

    def test_info_status_ignored(self):
        """Info status (empty string) is not alertable."""
        engine = AlertEngine()
        vitals = [_vital("RSSI", "-65 dBm", -65.0, "")]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert changes == []

    def test_multiple_alerts_same_asset(self):
        """Multiple metrics can fire independently."""
        engine = AlertEngine()
        vitals = [
            _vital("RSSI", "-85 dBm", -85.0, "warn"),
            _vital("TEMPERATURE", "70 °C", 70.0, "warn"),
        ]
        changes = engine.evaluate("RAD-01", "Trio #1", vitals)
        assert len(changes) == 2
        assert len(engine.open_alerts) == 2

    def test_different_assets_independent(self):
        """Alerts for different assets don't interfere."""
        engine = AlertEngine()
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        engine.evaluate("RAD-02", "Trio #2", [_vital("RSSI", "-95 dBm", -95.0, "bad")])
        assert len(engine.open_alerts) == 2

    def test_bool_alarm_fires(self):
        engine = AlertEngine()
        vitals = [_vital("HIGH PRESSURE ALARM", "ACTIVE", 1.0, "bad")]
        changes = engine.evaluate("RTU-01", "SCADAPack", vitals)
        assert len(changes) == 1
        assert changes[0].severity == "critical"


class TestAlertEngineOffline:
    """Tests for AlertEngine.evaluate_offline()."""

    def test_no_alert_when_fresh(self):
        engine = AlertEngine()
        now = datetime.now(UTC)
        result = engine.evaluate_offline("RAD-01", "Trio #1", now, poll_interval=30)
        assert result is None

    def test_fires_when_stale(self):
        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=200)
        result = engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30)
        assert result is not None
        assert result.severity == "critical"
        assert result.status == "open"

    def test_no_duplicate_offline(self):
        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=200)
        engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30)
        result = engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30)
        assert result is None

    def test_resolves_when_back(self):
        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=200)
        engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30)
        # Now it's back
        now = datetime.now(UTC)
        result = engine.evaluate_offline("RAD-01", "Trio #1", now, poll_interval=30)
        assert result is not None
        assert result.status == "resolved"

    def test_none_last_seen(self):
        engine = AlertEngine()
        result = engine.evaluate_offline("RAD-01", "Trio #1", None)
        assert result is None

    def test_tightened_default_threshold_rtu(self):
        """At the default 3x missed-polls threshold, a 5s-poll RTU
        should alarm well under 30s — the SCADAPack scenario from the
        comms-loss regression."""
        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=20)
        result = engine.evaluate_offline("RTU-01", "SCADAPack 470", old, poll_interval=5)
        assert result is not None
        assert result.severity == "critical"
        assert "comms loss" in result.message.lower()

    def test_explicit_missed_polls_override(self):
        """Caller can override the default threshold (e.g. for
        intentionally lossy links)."""
        engine = AlertEngine()
        # 80s stale, 30s poll: 2.6x missed. Default (3x=90s) → no alert.
        old = datetime.now(UTC) - timedelta(seconds=80)
        assert (
            engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30, missed_polls=3)
            is None
        )
        # Same staleness, override to 2x=60s → alert fires.
        assert (
            engine.evaluate_offline("RAD-01", "Trio #1", old, poll_interval=30, missed_polls=2)
            is not None
        )


class TestAlertEnginePartial:
    """Tests for AlertEngine.evaluate_partial() — partial-telemetry faults."""

    def test_no_alert_when_nothing_missing(self):
        engine = AlertEngine()
        result = engine.evaluate_partial("RTU-01", "SCADAPack", set())
        assert result is None
        assert len(engine.open_alerts) == 0

    def test_fires_when_metrics_missing(self):
        engine = AlertEngine()
        result = engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure", "vibration"})
        assert result is not None
        assert result.severity == "warning"
        assert result.status == "open"
        assert "partial telemetry" in result.message.lower()
        assert "suction_pressure" in result.message
        assert "vibration" in result.message

    def test_no_duplicate_partial(self):
        engine = AlertEngine()
        engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure"})
        result = engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure"})
        assert result is None
        assert len(engine.open_alerts) == 1

    def test_message_refreshes_when_gap_changes(self):
        """If the set of missing metrics changes while the alert is still
        open, the operator-facing message must update so they see the
        current gap."""
        engine = AlertEngine()
        engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure"})
        engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure", "vibration"})
        alert = engine.open_alerts[0]
        assert "vibration" in alert.message
        assert "2 metric" in alert.message

    def test_resolves_when_telemetry_restored(self):
        engine = AlertEngine()
        engine.evaluate_partial("RTU-01", "SCADAPack", {"suction_pressure"})
        result = engine.evaluate_partial("RTU-01", "SCADAPack", set())
        assert result is not None
        assert result.status == "resolved"
        assert result.resolved_at is not None
        assert len(engine.open_alerts) == 0

    def test_long_missing_list_truncated(self):
        """Message should preview the first few missing metrics and
        summarize the rest, not dump a wall of text."""
        engine = AlertEngine()
        missing = {f"metric_{i}" for i in range(20)}
        result = engine.evaluate_partial("RTU-01", "SCADAPack", missing)
        assert result is not None
        assert "+15 more" in result.message


class TestAlertEngineEvent:
    """Tests for AlertEngine.evaluate_event() — trap-driven alert path."""

    def test_cold_start_fires_warning(self):
        engine = AlertEngine()
        changes = engine.evaluate_event("RTR-01", "MikroTik L009", "coldStart", {})
        assert len(changes) == 1
        assert changes[0].severity == "warning"
        assert "cold start" in changes[0].message.lower()
        assert changes[0].asset_id == "RTR-01"

    def test_link_down_fires_critical(self):
        engine = AlertEngine()
        changes = engine.evaluate_event(
            "SW-01",
            "Cisco Catalyst 2960",
            "linkDown",
            {"1.3.6.1.2.1.2.2.1.1.5": 5},
        )
        assert len(changes) == 1
        assert changes[0].severity == "critical"
        assert "link down" in changes[0].message.lower()
        assert "ifIndex 5" in changes[0].message

    def test_link_up_resolves_link_down(self):
        """A linkUp trap on the same asset must auto-resolve the open
        linkDown alert and NOT fire its own alert."""
        engine = AlertEngine()
        engine.evaluate_event("SW-01", "Catalyst", "linkDown", {})
        assert len(engine.open_alerts) == 1
        changes = engine.evaluate_event("SW-01", "Catalyst", "linkUp", {})
        # The linkDown alert is in changes with status=resolved.
        assert any(a.status == "resolved" and "link" in a.message.lower() for a in changes)
        # No open link alerts remain.
        assert not any("link" in a.message.lower() for a in engine.open_alerts)

    def test_auth_failure_critical(self):
        engine = AlertEngine()
        changes = engine.evaluate_event("RTR-01", "MikroTik L009", "authenticationFailure", {})
        assert len(changes) == 1
        assert changes[0].severity == "critical"
        assert "authentication" in changes[0].message.lower()

    def test_unknown_oid_logs_but_no_alert(self):
        """Vendor-specific traps that we don't have a rule for should
        not crash and should not page anyone."""
        engine = AlertEngine()
        changes = engine.evaluate_event(
            "RAD-01",
            "Trio JR900",
            "1.3.6.1.4.1.5727.99.99.99",  # made-up vendor OID
            {},
        )
        assert changes == []
        assert len(engine.open_alerts) == 0

    def test_trap_auto_resolves_offline(self):
        """ANY trap from a previously-OFFLINE asset is proof of life and
        must auto-resolve the OFFLINE alert. This closes the feedback
        loop between the comms-loss path and the trap path."""
        from datetime import timedelta

        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=200)
        engine.evaluate_offline("RAD-01", "Trio JR900", old, poll_interval=30)
        assert len(engine.open_alerts) == 1

        changes = engine.evaluate_event("RAD-01", "Trio JR900", "coldStart", {})
        # Two state changes: OFFLINE resolved + new COLD_START fired.
        resolved = [c for c in changes if c.status == "resolved"]
        fired = [c for c in changes if c.status == "open"]
        assert len(resolved) == 1
        assert len(fired) == 1
        assert fired[0].message.lower().__contains__("cold start")

    def test_link_down_dedupes_on_reassertion(self):
        """If the same linkDown trap fires twice (flapping device), the
        second firing must not produce a duplicate alert."""
        engine = AlertEngine()
        first = engine.evaluate_event("SW-01", "Catalyst", "linkDown", {})
        second = engine.evaluate_event("SW-01", "Catalyst", "linkDown", {})
        assert len(first) == 1
        assert second == []
        assert len(engine.open_alerts) == 1


class TestAlertEngineReachability:
    """Tests for AlertEngine.evaluate_reachability() — Phase 2 ICMP."""

    def test_down_fires_critical(self):
        engine = AlertEngine()
        changes = engine.evaluate_reachability(
            "RTU-01", "SCADAPack 470", state="down", consecutive_failures=3
        )
        assert len(changes) == 1
        assert changes[0].severity == "critical"
        assert "unreachable" in changes[0].message.lower()

    def test_degraded_fires_warning(self):
        engine = AlertEngine()
        changes = engine.evaluate_reachability(
            "RTU-01",
            "SCADAPack 470",
            state="degraded",
            loss_pct=20.0,
            avg_rtt_ms=85.0,
        )
        assert len(changes) == 1
        assert changes[0].severity == "warning"
        assert "20.0%" in changes[0].message

    def test_up_resolves_both(self):
        """A return to 'up' must resolve any open down OR degraded alert."""
        engine = AlertEngine()
        engine.evaluate_reachability("RTU-01", "SCADAPack", "down", consecutive_failures=3)
        engine.evaluate_reachability("RTU-01", "SCADAPack", "degraded", loss_pct=15)
        # down already resolved degraded; only down remains.
        assert len(engine.open_alerts) == 1

        changes = engine.evaluate_reachability("RTU-01", "SCADAPack", "up")
        assert any(c.status == "resolved" for c in changes)
        assert engine.open_alerts == []

    def test_no_duplicate_down(self):
        engine = AlertEngine()
        engine.evaluate_reachability("RTU-01", "SCADAPack", "down", consecutive_failures=3)
        changes = engine.evaluate_reachability(
            "RTU-01", "SCADAPack", "down", consecutive_failures=4
        )
        assert changes == []
        assert len(engine.open_alerts) == 1

    def test_degraded_does_not_override_down(self):
        """A flapping condition that drops back to 'degraded' while
        we're already 'down' must not downgrade the alarm to warning."""
        engine = AlertEngine()
        engine.evaluate_reachability("RTU-01", "SCADAPack", "down", consecutive_failures=3)
        changes = engine.evaluate_reachability("RTU-01", "SCADAPack", "degraded", loss_pct=15)
        assert changes == []
        # Original critical alert still open.
        assert any(a.severity == "critical" for a in engine.open_alerts)

    def test_down_resolves_existing_degraded(self):
        """Escalation: degraded → down. The degraded warning must
        resolve so operators don't see two stacked alarms for the
        same condition."""
        engine = AlertEngine()
        engine.evaluate_reachability("RTU-01", "SCADAPack", "degraded", loss_pct=15)
        assert len(engine.open_alerts) == 1
        changes = engine.evaluate_reachability(
            "RTU-01", "SCADAPack", "down", consecutive_failures=3
        )
        # One new critical, one resolved warning.
        assert sum(1 for c in changes if c.status == "open") == 1
        assert sum(1 for c in changes if c.status == "resolved") == 1
        # Only the down alert remains open.
        open_severities = {a.severity for a in engine.open_alerts}
        assert open_severities == {"critical"}

    def test_icmp_up_resolves_offline(self):
        """ICMP coming back is proof-of-life and must auto-resolve the
        OFFLINE comms-loss alert too — same loop as the trap path."""
        from datetime import timedelta

        engine = AlertEngine()
        old = datetime.now(UTC) - timedelta(seconds=200)
        engine.evaluate_offline("RTU-01", "SCADAPack", old, poll_interval=5)
        assert any(a.message and "comms loss" in a.message.lower() for a in engine.open_alerts)

        changes = engine.evaluate_reachability("RTU-01", "SCADAPack", "up")
        resolved_offline = [
            c
            for c in changes
            if c.status == "resolved" and c.message and "comms loss" in c.message.lower()
        ]
        assert len(resolved_offline) == 1


class TestAlertEngineAcknowledge:
    """Tests for AlertEngine.acknowledge()."""

    def test_acknowledge_open_alert(self):
        engine = AlertEngine()
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        alert_id = engine.open_alerts[0].id
        result = engine.acknowledge(alert_id)
        assert result is not None
        assert result.status == "acknowledged"
        assert result.acknowledged_at is not None

    def test_acknowledge_nonexistent(self):
        engine = AlertEngine()
        result = engine.acknowledge("ALT-FAKE1234")
        assert result is None

    def test_acknowledge_already_acknowledged(self):
        """Can't re-acknowledge."""
        engine = AlertEngine()
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        alert_id = engine.open_alerts[0].id
        engine.acknowledge(alert_id)
        result = engine.acknowledge(alert_id)
        assert result is None


class TestAlertableMetrics:
    """Verify ALERTABLE_METRICS covers expected metrics."""

    def test_radio_metrics(self):
        assert "RSSI" in ALERTABLE_METRICS
        assert "SNR" in ALERTABLE_METRICS
        assert "TEMPERATURE" in ALERTABLE_METRICS

    def test_rtu_metrics(self):
        assert "SUCTION PRESSURE" in ALERTABLE_METRICS
        assert "DISCHARGE PRESSURE" in ALERTABLE_METRICS
        assert "BATTERY" in ALERTABLE_METRICS
        assert "VIBRATION" in ALERTABLE_METRICS

    def test_network_metrics(self):
        assert "CPU LOAD" in ALERTABLE_METRICS
        assert "RX ERRORS" in ALERTABLE_METRICS

    def test_alarms(self):
        assert "HIGH PRESSURE ALARM" in ALERTABLE_METRICS
        assert "LOW BATTERY ALARM" in ALERTABLE_METRICS
        assert "COMM FAULT" in ALERTABLE_METRICS
