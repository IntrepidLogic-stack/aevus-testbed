"""Trade-secret discipline tests for the pearl API (Task #199).

═══════════════════════════════════════════════════════════════════════════
THE ATTACK WE'RE DEFENDING AGAINST
═══════════════════════════════════════════════════════════════════════════
The pearl scoring algorithm and per-device-class normalization weights are
IL proprietary (see src/engine/pearl_score.py module docstring). The defense
against sample-poll reverse-engineering is API design: we expose ONLY the
final 0-100 score and status band, NEVER the raw input vitals that fed
the curve. Anyone polling the endpoint cannot reconstruct the function
from the output alone.

These tests are the regression guard. If a future contributor adds raw
vitals to the pearl response (intentionally or accidentally), CI fails
before the change can ship.
"""

from __future__ import annotations

from typing import Any

from src.api.pearls import _pearl_for, _sim_pearl

# Exactly these keys are allowed in a pearl response, no more, no less.
ALLOWED_PEARL_KEYS = {
    "pearl_id",
    "label",
    "asset_id",
    "asset_label",
    "score",
    "status",
    "last_update",
    "drill_url",
    "simulated",  # only on sim pearls
}

# Substrings that, if found in a JSON value, indicate a raw-input leak.
FORBIDDEN_INPUT_TOKENS = [
    "rssi",
    "voltage",
    "battery",
    "cpu_load",
    "memory_used",
    "temperature",
    "latency_ms",
    "tx_errors",
    "rx_errors",
    "raw_value",
    "_weight",
    "_curve",
    "_threshold",
    "piecewise",
]


def _flatten_strings(obj: Any) -> list[str]:
    """Recursively collect every string value from a JSON-like dict/list."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k).lower())
            out.extend(_flatten_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_flatten_strings(item))
    elif isinstance(obj, str):
        out.append(obj.lower())
    return out


class TestPearlResponseShape:
    """The wire format must be exactly the documented shape."""

    def test_real_pearl_keys_are_allowed(self):
        pearl = _pearl_for("efm_rtu", "EFM/RTU/PLC", None)
        unexpected = set(pearl.keys()) - ALLOWED_PEARL_KEYS
        assert not unexpected, f"Unexpected keys in pearl response: {unexpected}"

    def test_sim_pearl_keys_are_allowed(self):
        pearl = _sim_pearl("mst_radio", "Master Radio", 52)
        unexpected = set(pearl.keys()) - ALLOWED_PEARL_KEYS
        assert not unexpected, f"Unexpected keys in sim pearl response: {unexpected}"

    def test_real_pearl_has_required_keys(self):
        pearl = _pearl_for("efm_rtu", "EFM/RTU/PLC", None)
        required = {"pearl_id", "label", "asset_id", "score", "status", "last_update", "drill_url"}
        missing = required - set(pearl.keys())
        assert not missing, f"Missing required keys in pearl response: {missing}"


class TestNoRawVitalLeak:
    """The killer test — scan every value in the response for raw-input tokens."""

    def test_offline_pearl_leaks_nothing(self):
        pearl = _pearl_for("efm_rtu", "EFM/RTU/PLC", None)
        strings = _flatten_strings(pearl)
        for token in FORBIDDEN_INPUT_TOKENS:
            for s in strings:
                assert token not in s, (
                    f"Forbidden raw-input token '{token}' leaked into pearl "
                    f"response value '{s}'. The pearl API must never echo raw "
                    f"vitals — only the final score + status."
                )

    def test_sim_pearl_leaks_nothing(self):
        for profile_score in [94, 52, 18]:
            pearl = _sim_pearl("sub_radio", "Subscriber Radio", profile_score)
            strings = _flatten_strings(pearl)
            for token in FORBIDDEN_INPUT_TOKENS:
                for s in strings:
                    assert token not in s, (
                        f"Forbidden token '{token}' leaked into sim pearl: {s}"
                    )

    def test_sim_pearl_score_is_a_number_not_a_computation(self):
        """Sim pearls must NOT expose the formula by leaking intermediate
        computations like 'rssi * 0.4 + temp * 0.15'."""
        pearl = _sim_pearl("mst_radio", "Master Radio", 52)
        assert isinstance(pearl["score"], int)
        # If score were ever set from a formula expression string, this would catch it
        assert not isinstance(pearl["score"], str)


class TestStatusBandOnly:
    """Status must be one of the four documented bands. Don't leak custom
    debug states like 'computing' or 'piecewise_below_anchor'."""

    def test_real_pearl_status_is_canonical(self):
        pearl = _pearl_for("efm_rtu", "EFM/RTU/PLC", None)
        assert pearl["status"] in {"good", "warn", "bad", "offline"}

    def test_sim_pearl_statuses_are_canonical(self):
        for score in [95, 75, 50, 25, 5]:
            pearl = _sim_pearl("test", "Test", score)
            assert pearl["status"] in {"good", "warn", "bad", "offline"}
