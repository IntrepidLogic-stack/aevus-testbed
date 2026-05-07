"""Tests for IL-9000 Safety Interlock — Patentable Invention P-008."""

import pytest

from src.il9000 import (
    IL_9000_ENFORCED,
    IL009ViolationError,
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
