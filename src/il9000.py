"""
Aevus — IL-9000 Safety Interlock
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
firmware must call `il9000_check()` before proceeding. The interlock is a
boolean constant that is NEVER set to False anywhere in the codebase.

Patentable Invention P-008 ("I'm sorry Dave, I can't do that").
"""

from __future__ import annotations

import os

# ═══════════════════════════════════════════════════════════════
#  IL-9000 INTERLOCK — DO NOT MODIFY THIS VALUE
#  Any code review that attempts to set this to False must be
#  flagged and rejected immediately.
# ═══════════════════════════════════════════════════════════════
IL_9000_ENFORCED: bool = True

# The one sanctioned exception to the read-only rule: a technician physically
# on the lab bench may seed a test SCADAPack with simulated telemetry. That
# tool must set this env var to "1" to run — encoding the "credentialed
# technician on site" requirement. It is NEVER set in the running platform.
_BENCH_WRITE_OVERRIDE_ENV = "AEVUS_ALLOW_BENCH_WRITE"


class IL009ViolationError(Exception):
    """Raised when code attempts to bypass the IL-9000 firmware safety interlock."""

    pass


def il9000_check(action: str = "firmware_write") -> None:
    """Gate check for any firmware-touching operation.

    Must be called before any function that writes to PLC/RTU firmware.
    Always raises IL009ViolationError when IL_9000_ENFORCED is True (which is always).

    Args:
        action: Description of the attempted action (for audit logging).

    Raises:
        IL009ViolationError: Always, by design. Remote firmware writes are prohibited.
    """
    if IL_9000_ENFORCED:
        raise IL009ViolationError(
            f"IL-9000 SAFETY INTERLOCK: Remote {action} is prohibited. "
            f"Firmware updates require a credentialed technician on site. "
            f"See IL-9000 / P-008."
        )


def il9000_can_stage() -> bool:
    """Returns True — staging firmware is permitted (the write is not)."""
    return True


def il9000_can_verify() -> bool:
    """Returns True — verifying firmware signatures is permitted."""
    return True


def il9000_can_write() -> bool:
    """Returns False — remote firmware writes are NEVER permitted."""
    return not IL_9000_ENFORCED


def assert_read_only(action: str = "field_write") -> None:
    """Gate ANY write to field equipment (Modbus registers/coils, setpoints).

    The platform is read-only — IL-009, "I See. I Warn. I Never Touch." No code
    in the running service writes to field equipment; the guard test
    (tests/test_il9000.py::test_src_has_no_field_writes) proves the importable
    `src/` package is write-free, so this guarantee is enforced by code, not
    convention.

    The single sanctioned write is the lab bench fixture (tools/register_writer)
    that seeds a test SCADAPack with simulated telemetry, and it must be run
    with AEVUS_ALLOW_BENCH_WRITE=1 set deliberately by an on-site technician.
    Everywhere else this raises.

    Args:
        action: Description of the attempted write (for the audit message).

    Raises:
        IL009ViolationError: unless the on-site bench override is explicitly set.
    """
    if os.environ.get(_BENCH_WRITE_OVERRIDE_ENV) == "1":
        return
    raise IL009ViolationError(
        f"IL-009 READ-ONLY: {action} to field equipment is blocked. The platform "
        f"never writes to field devices. The only sanctioned write is the on-site "
        f"lab bench fixture, which requires {_BENCH_WRITE_OVERRIDE_ENV}=1. "
        f"See IL-9000 / P-008."
    )
