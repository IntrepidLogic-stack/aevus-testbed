"""Aevus device collectors.

Module-level imports are intentionally minimal — only ``BaseCollector``
loads at package import time. Concrete collectors live in their own
modules and pull in optional protocol libraries (pysnmp, pymodbus,
icmplib, dnp3-python) only when imported by name.

Why: each Greengrass component packages only the collector it runs,
with only its own dependencies. Eager-importing every collector here
would force every component to install every library — defeating the
per-component packaging design (and the same logic was annoying for
unit tests, which previously had to stub the missing modules).

Use:
    from src.collectors.snmp_trap_receiver import SNMPTrapReceiver
    from src.collectors.icmp_probe import ICMPProbe
    from src.collectors.dnp3_unsolicited import DNP3UnsolicitedReceiver
    from src.collectors.modbus_rtu import SCADAPack470Collector
    # ...etc.
"""

from src.collectors.base import BaseCollector

__all__ = ["BaseCollector"]
