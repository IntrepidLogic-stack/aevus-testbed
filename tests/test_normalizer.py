"""Tests for the telemetry normalizer engine."""

from datetime import UTC, datetime

from src.engine.normalizer import evaluate_status, normalize_batch, normalize_reading
from src.models.telemetry import RawTelemetry

# ── evaluate_status ──


class TestEvaluateStatus:
    """Tests for threshold-based status evaluation."""

    def test_info_always_empty(self):
        assert evaluate_status(999.0, "info") == ""

    def test_bool_bad_active(self):
        assert evaluate_status(1.0, "bool_bad") == "bad"

    def test_bool_bad_inactive(self):
        assert evaluate_status(0.0, "bool_bad") == "good"

    def test_bool_good_active(self):
        """1.0 = healthy (e.g. link_state LINKED). Task #155 regression test."""
        assert evaluate_status(1.0, "bool_good") == "good"

    def test_bool_good_inactive(self):
        """0.0 = down. The 'ACTIVE radio mislabeled as bad' bug."""
        assert evaluate_status(0.0, "bool_good") == "bad"

    def test_lower_bad_good(self):
        """RSSI at -65 dBm is good (above -80 warn)."""
        assert evaluate_status(-65.0, "lower_bad", warn=-80.0, crit=-90.0) == "good"

    def test_lower_bad_warn(self):
        """RSSI at -85 dBm is warn (below -80 but above -90)."""
        assert evaluate_status(-85.0, "lower_bad", warn=-80.0, crit=-90.0) == "warn"

    def test_lower_bad_critical(self):
        """RSSI at -95 dBm is bad (below -90)."""
        assert evaluate_status(-95.0, "lower_bad", warn=-80.0, crit=-90.0) == "bad"

    def test_lower_bad_at_warn_boundary(self):
        """Exactly at warn threshold is warn."""
        assert evaluate_status(-80.0, "lower_bad", warn=-80.0, crit=-90.0) == "warn"

    def test_lower_bad_at_crit_boundary(self):
        """Exactly at crit threshold is bad."""
        assert evaluate_status(-90.0, "lower_bad", warn=-80.0, crit=-90.0) == "bad"

    def test_upper_bad_good(self):
        """Temperature at 40C is good (below 60 warn)."""
        assert evaluate_status(40.0, "upper_bad", warn=60.0, crit=75.0) == "good"

    def test_upper_bad_warn(self):
        """Temperature at 65C is warn."""
        assert evaluate_status(65.0, "upper_bad", warn=60.0, crit=75.0) == "warn"

    def test_upper_bad_critical(self):
        """Temperature at 80C is bad."""
        assert evaluate_status(80.0, "upper_bad", warn=60.0, crit=75.0) == "bad"

    def test_upper_bad_at_warn_boundary(self):
        assert evaluate_status(60.0, "upper_bad", warn=60.0, crit=75.0) == "warn"

    def test_upper_bad_at_crit_boundary(self):
        assert evaluate_status(75.0, "upper_bad", warn=60.0, crit=75.0) == "bad"

    def test_missing_thresholds_returns_empty(self):
        assert evaluate_status(50.0, "lower_bad", warn=None, crit=None) == ""

    def test_unknown_direction_returns_empty(self):
        assert evaluate_status(50.0, "unknown_direction", warn=10.0, crit=5.0) == ""


# ── normalize_reading ──


def _make_reading(metric: str, value: float, unit: str = "dBm") -> RawTelemetry:
    return RawTelemetry(
        asset_id="RAD-01",
        metric=metric,
        value=value,
        unit=unit,
        timestamp=datetime.now(UTC),
        source="simulator",
    )


class TestNormalizeReading:
    """Tests for converting raw readings to vitals."""

    def test_rssi_good(self):
        vital = normalize_reading(_make_reading("rssi", -65.0, "dBm"))
        assert vital.label == "RSSI"
        assert vital.status == "good"
        assert vital.raw_value == -65.0
        assert "dBm" in vital.value

    def test_rssi_warn(self):
        vital = normalize_reading(_make_reading("rssi", -85.0, "dBm"))
        assert vital.status == "warn"

    def test_rssi_bad(self):
        vital = normalize_reading(_make_reading("rssi", -95.0, "dBm"))
        assert vital.status == "bad"

    def test_temperature_good(self):
        vital = normalize_reading(_make_reading("temperature", 35.0, "°C"))
        assert vital.label == "TEMPERATURE"
        assert vital.status == "good"

    def test_temperature_warn(self):
        vital = normalize_reading(_make_reading("temperature", 65.0, "°C"))
        assert vital.status == "warn"

    def test_temperature_bad(self):
        vital = normalize_reading(_make_reading("temperature", 80.0, "°C"))
        assert vital.status == "bad"

    def test_battery_good(self):
        vital = normalize_reading(_make_reading("battery_voltage", 13.5, "VDC"))
        assert vital.label == "BATTERY"
        assert vital.status == "good"

    def test_battery_warn(self):
        vital = normalize_reading(_make_reading("battery_voltage", 11.8, "VDC"))
        assert vital.status == "warn"

    def test_battery_bad(self):
        vital = normalize_reading(_make_reading("battery_voltage", 11.0, "VDC"))
        assert vital.status == "bad"

    def test_bool_alarm_active(self):
        vital = normalize_reading(_make_reading("high_pressure_alarm", 1.0, ""))
        assert vital.label == "HIGH PRESSURE ALARM"
        assert vital.status == "bad"
        assert vital.value == "ACTIVE"

    def test_bool_alarm_inactive(self):
        vital = normalize_reading(_make_reading("high_pressure_alarm", 0.0, ""))
        assert vital.status == "good"
        assert vital.value == "OK"

    def test_compressor_running(self):
        vital = normalize_reading(_make_reading("compressor_running", 1.0, ""))
        assert vital.value == "RUNNING"

    def test_compressor_stopped(self):
        vital = normalize_reading(_make_reading("compressor_running", 0.0, ""))
        assert vital.value == "STOPPED"

    def test_info_metric_no_status(self):
        vital = normalize_reading(_make_reading("tx_power", 20.0, "dBm"))
        assert vital.label == "TX POWER"
        assert vital.status == ""

    def test_unknown_metric_passes_through(self):
        vital = normalize_reading(_make_reading("some_new_thing", 42.0, "units"))
        assert vital.label == "SOME NEW THING"
        assert vital.status == ""
        assert vital.raw_value == 42.0

    def test_vibration_good(self):
        vital = normalize_reading(_make_reading("vibration", 2.0, "mm/s"))
        assert vital.status == "good"

    def test_vibration_warn(self):
        vital = normalize_reading(_make_reading("vibration", 5.0, "mm/s"))
        assert vital.status == "warn"

    def test_vibration_bad(self):
        vital = normalize_reading(_make_reading("vibration", 8.0, "mm/s"))
        assert vital.status == "bad"


# ── normalize_batch ──


class TestNormalizeBatch:
    """Tests for batch normalization."""

    def test_empty_batch(self):
        assert normalize_batch([]) == []

    def test_batch_preserves_order(self):
        readings = [
            _make_reading("rssi", -65.0, "dBm"),
            _make_reading("snr", 20.0, "dB"),
            _make_reading("temperature", 35.0, "°C"),
        ]
        vitals = normalize_batch(readings)
        # 3 inputs + derived FADE MARGIN (appended because the batch has rssi)
        assert len(vitals) == 4
        assert vitals[0].label == "RSSI"
        assert vitals[1].label == "SNR"
        assert vitals[2].label == "TEMPERATURE"
        assert vitals[3].label == "FADE MARGIN"

    def test_batch_skips_bad_readings(self):
        """Batch should not crash on malformed readings."""
        readings = [
            _make_reading("rssi", -65.0, "dBm"),
            _make_reading("snr", 20.0, "dB"),
        ]
        vitals = normalize_batch(readings)
        # 2 inputs + derived FADE MARGIN from the rssi reading
        assert len(vitals) == 3


# ── fade margin derivation (P3 contract #1) ──


class TestFadeMargin:
    """Fade margin = RSSI − receiver sensitivity: the engineering-honest
    radio metric. -71 dBm on a -108 dBm-sensitivity JR900 is ~37 dB of
    margin — an excellent path that must never render as a warning."""

    def test_derived_from_rssi_batch(self):
        vitals = normalize_batch([_make_reading("rssi", -71.0, "dBm")])
        fade = next(v for v in vitals if v.label == "FADE MARGIN")
        assert fade.raw_value == 37.0  # -71 − (-108)
        assert fade.unit == "dB"
        assert fade.status == "good"  # ≥30 dB

    def test_warn_band(self):
        """25 dB margin: below the 30 dB comfortable floor, above 20 crit."""
        vitals = normalize_batch([_make_reading("rssi", -83.0, "dBm")])
        fade = next(v for v in vitals if v.label == "FADE MARGIN")
        assert fade.raw_value == 25.0
        assert fade.status == "warn"

    def test_crit_band(self):
        """12 dB margin: below the 20 dB rural design minimum."""
        vitals = normalize_batch([_make_reading("rssi", -96.0, "dBm")])
        fade = next(v for v in vitals if v.label == "FADE MARGIN")
        assert fade.raw_value == 12.0
        assert fade.status == "bad"

    def test_no_rssi_no_fade(self):
        """Non-radio batches gain nothing."""
        vitals = normalize_batch([_make_reading("suction_pressure", 245.0, "PSI")])
        assert all(v.label != "FADE MARGIN" for v in vitals)
