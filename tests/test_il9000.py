"""Tests for IL-9000 Safety Interlock — Patentable Invention P-008."""

import pathlib

import pytest

from src.il9000 import (
    IL_9000_ENFORCED,
    IL009ViolationError,
    assert_read_only,
    il9000_can_stage,
    il9000_can_verify,
    il9000_can_write,
    il9000_check,
)


class TestIL009Interlock:
    """IL-9000: Remote firmware writes must ALWAYS be blocked."""

    def test_interlock_is_enforced(self):
        """IL_9000_ENFORCED must always be True."""
        assert IL_9000_ENFORCED is True

    def test_firmware_write_blocked(self):
        """il9000_check() must raise on any firmware write attempt."""
        with pytest.raises(IL009ViolationError, match="IL-9000 SAFETY INTERLOCK"):
            il9000_check("firmware_write")

    def test_firmware_write_blocked_custom_action(self):
        """il9000_check() includes the action name in the error."""
        with pytest.raises(IL009ViolationError, match="plc_flash"):
            il9000_check("plc_flash")

    def test_staging_permitted(self):
        """Staging firmware is allowed (only the final write is blocked)."""
        assert il9000_can_stage() is True

    def test_verification_permitted(self):
        """Verifying firmware signatures is allowed."""
        assert il9000_can_verify() is True

    def test_write_always_false(self):
        """il9000_can_write() must always return False."""
        assert il9000_can_write() is False

    def test_constant_is_bool_true(self):
        """IL_9000_ENFORCED must be exactly bool True, not truthy."""
        assert type(IL_9000_ENFORCED) is bool
        assert IL_9000_ENFORCED == True  # noqa: E712


class TestReadOnlyInterlock:
    """IL-009 ("I never touch"): the platform never writes to field equipment."""

    def test_field_write_blocked_by_default(self, monkeypatch):
        """assert_read_only() raises with no on-site override present."""
        monkeypatch.delenv("AEVUS_ALLOW_BENCH_WRITE", raising=False)
        with pytest.raises(IL009ViolationError, match="READ-ONLY"):
            assert_read_only("modbus_register_write")

    def test_action_name_in_error(self, monkeypatch):
        """The attempted action appears in the violation message (audit)."""
        monkeypatch.delenv("AEVUS_ALLOW_BENCH_WRITE", raising=False)
        with pytest.raises(IL009ViolationError, match="valve_setpoint"):
            assert_read_only("valve_setpoint")

    def test_bench_override_permits_write(self, monkeypatch):
        """The explicit on-site bench override is the one sanctioned exception."""
        monkeypatch.setenv("AEVUS_ALLOW_BENCH_WRITE", "1")
        assert_read_only("scadapack_bench_seed_write")  # must not raise

    def test_src_has_no_field_writes(self):
        """CODE-ENFORCED read-only guarantee: the importable app package (src/)
        must contain NO Modbus/field write call. This is what makes IL-009
        "enforced by code, not policy" — if a future change adds a write into
        any collector/engine/API, this test fails in CI. The only sanctioned
        write lives in the gated bench fixture under tools/, outside src/.
        """
        src = pathlib.Path(__file__).resolve().parent.parent / "src"
        write_calls = (".write_register(", ".write_registers(", ".write_coil(", ".write_coils(")
        offenders = []
        for py in src.rglob("*.py"):
            text = py.read_text()
            for call in write_calls:
                if call in text:
                    offenders.append(f"{py.relative_to(src.parent)}{call}")
        assert not offenders, (
            "IL-009 read-only violation — field-write call(s) found in src/:\n  "
            + "\n  ".join(offenders)
            + "\nField writes belong only in the gated bench tool under tools/, "
            "never in the importable app package."
        )
