"""Tests for IL-009 Safety Interlock — Patentable Invention P-008."""

import pytest

from src.il009 import (
    IL_009_ENFORCED,
    IL009ViolationError,
    il009_can_stage,
    il009_can_verify,
    il009_can_write,
    il009_check,
)


class TestIL009Interlock:
    """IL-009: Remote firmware writes must ALWAYS be blocked."""

    def test_interlock_is_enforced(self):
        """IL_009_ENFORCED must always be True."""
        assert IL_009_ENFORCED is True

    def test_firmware_write_blocked(self):
        """il009_check() must raise on any firmware write attempt."""
        with pytest.raises(IL009ViolationError, match="IL-009 SAFETY INTERLOCK"):
            il009_check("firmware_write")

    def test_firmware_write_blocked_custom_action(self):
        """il009_check() includes the action name in the error."""
        with pytest.raises(IL009ViolationError, match="plc_flash"):
            il009_check("plc_flash")

    def test_staging_permitted(self):
        """Staging firmware is allowed (only the final write is blocked)."""
        assert il009_can_stage() is True

    def test_verification_permitted(self):
        """Verifying firmware signatures is allowed."""
        assert il009_can_verify() is True

    def test_write_always_false(self):
        """il009_can_write() must always return False."""
        assert il009_can_write() is False

    def test_constant_is_bool_true(self):
        """IL_009_ENFORCED must be exactly bool True, not truthy."""
        assert type(IL_009_ENFORCED) is bool
        assert IL_009_ENFORCED == True  # noqa: E712
