"""Tests for the ingest → historian persistence path (Task #196).

Before this fix, /ingest stored vitals in-memory only and the TRENDS
button always showed 'no historian samples yet' for edge-pushed assets.
These tests verify the vitals→RawTelemetry conversion handles both
payload shapes and never raises (best-effort discipline).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api.ingest import _persist_to_historian


def _mock_app_state_with_influx():
    """Patch src.main.app_state with a mock influx that records readings."""
    mock_influx = MagicMock()
    mock_state = MagicMock()
    mock_state.influx = mock_influx
    return mock_state, mock_influx


class TestPersistToHistorian:
    def test_numeric_vitals_converted(self):
        state, influx = _mock_app_state_with_influx()
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=state)}):
            n = _persist_to_historian("RAD-01", {"RSSI": -65.0, "TEMPERATURE": 38.5})
        assert n == 2
        influx.write_readings.assert_called_once()
        readings = influx.write_readings.call_args[0][0]
        assert {r.metric for r in readings} == {"rssi", "temperature"}
        assert all(r.source == "relay" for r in readings)

    def test_dict_shape_vitals_converted(self):
        state, influx = _mock_app_state_with_influx()
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=state)}):
            n = _persist_to_historian(
                "RTU-01",
                {"SUCTION PRESSURE": {"value": 245.3, "unit": "PSI"}},
            )
        assert n == 1
        readings = influx.write_readings.call_args[0][0]
        assert readings[0].metric == "suction_pressure"
        assert readings[0].value == 245.3
        assert readings[0].unit == "PSI"

    def test_non_numeric_vitals_skipped(self):
        state, influx = _mock_app_state_with_influx()
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=state)}):
            n = _persist_to_historian("RAD-01", {"LINK STATE": "LINKED", "RSSI": -70})
        # Only the numeric RSSI should persist; the string is skipped
        assert n == 1

    def test_empty_vitals_writes_nothing(self):
        state, influx = _mock_app_state_with_influx()
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=state)}):
            n = _persist_to_historian("RAD-01", {})
        assert n == 0
        influx.write_readings.assert_not_called()

    def test_influx_failure_never_raises(self):
        """Best-effort: an influx exception must return 0, not propagate."""
        state, influx = _mock_app_state_with_influx()
        influx.write_readings.side_effect = RuntimeError("influx down")
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=state)}):
            n = _persist_to_historian("RAD-01", {"RSSI": -65})
        assert n == 0  # swallowed, did not raise

    def test_missing_influx_returns_zero(self):
        mock_state = MagicMock()
        mock_state.influx = None
        with patch.dict("sys.modules", {"src.main": MagicMock(app_state=mock_state)}):
            n = _persist_to_historian("RAD-01", {"RSSI": -65})
        assert n == 0
