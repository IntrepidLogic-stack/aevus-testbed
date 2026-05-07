"""
Aevus — IL-009 Safety Interlock
================================
HARD SAFETY RULE: PLC/RTU firmware updates are NEVER automated remotely.

The platform can:
  - Track firmware versions
  - Stage updates
  - Verify signatures
  - Schedule change windows
  - Prepare rollback artifacts
  - Report compliance

The platform CANNOT:
  - Execute the final firmware write

That requires a credentialed technician physically on site.

This is enforced by code (not policy). Any function that touches PLC/RTU
firmware must call `il009_check()` before proceeding. The interlock is a
boolean constant that is NEVER set to False anywhere in the codebase.

Patentable Invention P-008.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
#  IL-009 INTERLOCK — DO NOT MODIFY THIS VALUE
#  Any code review that attempts to set this to False must be
#  flagged and rejected immediately.
# ═══════════════════════════════════════════════════════════════
IL_009_ENFORCED: bool = True


class IL009ViolationError(Exception):
    """Raised when code attempts to bypass the IL-009 firmware safety interlock."""

    pass


def il009_check(action: str = "firmware_write") -> None:
    """Gate check for any firmware-touching operation.

    Must be called before any function that writes to PLC/RTU firmware.
    Always raises IL009ViolationError when IL_009_ENFORCED is True (which is always).

    Args:
        action: Description of the attempted action (for audit logging).

    Raises:
        IL009ViolationError: Always, by design. Remote firmware writes are prohibited.
    """
    if IL_009_ENFORCED:
        raise IL009ViolationError(
            f"IL-009 SAFETY INTERLOCK: Remote {action} is prohibited. "
            f"Firmware updates require a credentialed technician on site. "
            f"See IL-009 / P-008."
        )


def il009_can_stage() -> bool:
    """Returns True — staging firmware is permitted (the write is not)."""
    return True


def il009_can_verify() -> bool:
    """Returns True — verifying firmware signatures is permitted."""
    return True


def il009_can_write() -> bool:
    """Returns False — remote firmware writes are NEVER permitted."""
    return not IL_009_ENFORCED
