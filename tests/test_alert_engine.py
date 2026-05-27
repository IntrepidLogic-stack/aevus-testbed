"""Tests for the stateful alert engine."""

from datetime import UTC, datetime, timedelta

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


class TestAcknowledgeSQLiteFallback:
    """Test that acknowledge falls back to SQLite when alert not in memory."""

    def test_acknowledge_from_sqlite(self):
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from src.models.alert import Alert

        engine = AlertEngine()
        mock_db = MagicMock()
        mock_alert = Alert(
            id="ALT-DBONLY",
            severity="warning",
            asset_id="RTR-01",
            asset_name="MikroTik L009",
            message="test alert",
            detected_at=datetime.now(UTC),
            status="open",
        )
        mock_db.get_alert.return_value = mock_alert

        # Alert is NOT in memory, but IS in SQLite
        result = engine.acknowledge("ALT-DBONLY", db=mock_db)
        assert result is not None
        assert result.status == "acknowledged"
        assert result.acknowledged_at is not None
        mock_db.get_alert.assert_called_once_with("ALT-DBONLY")

    def test_acknowledge_sqlite_already_acknowledged(self):
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from src.models.alert import Alert

        engine = AlertEngine()
        mock_db = MagicMock()
        mock_alert = Alert(
            id="ALT-ACKED",
            severity="warning",
            asset_id="RTR-01",
            asset_name="MikroTik L009",
            message="test alert",
            detected_at=datetime.now(UTC),
            status="acknowledged",
        )
        mock_db.get_alert.return_value = mock_alert

        # Alert exists in DB but already acknowledged
        result = engine.acknowledge("ALT-ACKED", db=mock_db)
        assert result is None

    def test_acknowledge_not_in_memory_or_db(self):
        from unittest.mock import MagicMock

        engine = AlertEngine()
        mock_db = MagicMock()
        mock_db.get_alert.return_value = None

        result = engine.acknowledge("ALT-GHOST", db=mock_db)
        assert result is None

    def test_acknowledge_no_db_fallback(self):
        """Without db param, only checks in-memory."""
        engine = AlertEngine()
        result = engine.acknowledge("ALT-MISSING")
        assert result is None


class TestChatteringDetection:
    """ISA-18.2 §7.5 — repeated fires within window emit meta-alarm + auto-shelve."""

    def _flap_once(self, engine: AlertEngine) -> None:
        """Drive one fire/clear cycle of a warn condition on RAD-01.RSSI."""
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-85 dBm", -85.0, "warn")])
        engine.evaluate("RAD-01", "Trio #1", [_vital("RSSI", "-65 dBm", -65.0, "good")])

    def test_below_threshold_no_meta_alarm(self):
        engine = AlertEngine()
        for _ in range(5):  # CHATTER_THRESHOLD = 5 — exactly at, not above
            self._flap_once(engine)
        meta = [a for a in engine.open_alerts if a.id.startswith("CHAT-")]
        assert meta == []
        assert not engine.is_shelved("RAD-01", "RSSI")

    def test_threshold_crossed_emits_meta_and_shelves(self):
        engine = AlertEngine()
        for _ in range(6):  # one past CHATTER_THRESHOLD
            self._flap_once(engine)
        meta = [a for a in engine.open_alerts if a.id.startswith("CHAT-")]
        assert len(meta) == 1
        assert meta[0].severity == "warning"
        assert "chattering" in meta[0].message.lower()
        assert engine.is_shelved("RAD-01", "RSSI")

    def test_shelved_key_does_not_fire_new_alerts(self):
        engine = AlertEngine()
        engine.shelve("RAD-01", "RSSI", duration_s=600, reason="maintenance")
        changes = engine.evaluate(
            "RAD-01", "Trio #1", [_vital("RSSI", "-95 dBm", -95.0, "bad")]
        )
        assert changes == []

    def test_shelf_expires(self):
        engine = AlertEngine()
        engine.shelve("RAD-01", "RSSI", duration_s=600)
        # Force expiry by manipulating internal state
        engine._shelved_until[("RAD-01", "RSSI")] = datetime.now(UTC) - timedelta(seconds=1)
        assert not engine.is_shelved("RAD-01", "RSSI")
        # And further evaluation now fires normally
        changes = engine.evaluate(
            "RAD-01", "Trio #1", [_vital("RSSI", "-95 dBm", -95.0, "bad")]
        )
        assert len(changes) == 1

    def test_meta_alarm_not_double_emitted(self):
        engine = AlertEngine()
        for _ in range(8):  # well past threshold
            self._flap_once(engine)
        meta = [a for a in engine.open_alerts if a.id.startswith("CHAT-")]
        assert len(meta) == 1  # one, not many


class TestRecordEvent:
    """One-shot event alarms (firmware change, maintenance due, SNMP traps)."""

    def test_emits_alert_for_first_event(self):
        engine = AlertEngine()
        alert = engine.record_event(
            "SW-01", "Catalyst 2960", "FIRMWARE_CHANGED", "version v12 → v15", severity="info"
        )
        assert alert is not None
        assert alert.id.startswith("EVT-")
        assert alert.status == "open"
        assert alert.severity == "info"
        assert "v12 → v15" in alert.message

    def test_dedupes_open_event(self):
        engine = AlertEngine()
        engine.record_event("SW-01", "Catalyst", "FIRMWARE_CHANGED", "x", severity="info")
        again = engine.record_event("SW-01", "Catalyst", "FIRMWARE_CHANGED", "y", severity="info")
        assert again is None
        assert len(engine.open_alerts) == 1

    def test_shelve_suppresses_event(self):
        engine = AlertEngine()
        engine.shelve("SW-01", "FIRMWARE_CHANGED", duration_s=600)
        alert = engine.record_event("SW-01", "Catalyst", "FIRMWARE_CHANGED", "x")
        assert alert is None

    def test_different_event_types_independent(self):
        engine = AlertEngine()
        a = engine.record_event("RTU-01", "SCADAPack", "FIRMWARE_CHANGED", "x")
        b = engine.record_event("RTU-01", "SCADAPack", "MAINTENANCE_DUE", "y", severity="warning")
        assert a is not None
        assert b is not None
        assert a.id != b.id
