"""
Aevus — SNMP CLI transport mixin.

The four SNMP collectors (radio, router, switch, edge) all shell out to the
net-snmp `snmpget`/`snmpwalk` binaries via `asyncio.to_thread`. Before this, each
copy-pasted the same `_snmp_get` / `_snmp_get_sync` / `_snmp_walk_sync` (and the
timeticks + walk-value parsing) — 3-4 identical copies that drift independently
(docs/ARCHITECTURE_REVIEW_2026-07.md, H4). This mixin holds the single copy.

Mix it in ALONGSIDE BaseCollector — it relies on `self.host`, `self.community`,
and `self.log` set by BaseCollector.__init__:

    class SNMPSwitchCollector(SNMPCliMixin, BaseCollector): ...
"""

from __future__ import annotations

import asyncio
import subprocess


class SNMPCliMixin:
    """Shared net-snmp CLI helpers for SNMP collectors."""

    # Set by BaseCollector.__init__ / the concrete collector.
    host: str
    community: str

    async def _snmp_get(self, oid: str) -> str | None:
        """Get a single OID value (off the event loop)."""
        return await asyncio.to_thread(self._snmp_get_sync, oid)

    async def _snmp_walk(self, base_oid: str = "") -> dict[str, str]:
        """Walk an OID subtree (off the event loop)."""
        return await asyncio.to_thread(self._snmp_walk_sync, base_oid)

    def _snmp_get_sync(self, oid: str) -> str | None:
        """Synchronous SNMP GET via the `snmpget` CLI. Returns the bare value
        (type prefix and surrounding quotes stripped) or None on any failure."""
        try:
            result = subprocess.run(
                ["snmpget", "-v2c", "-c", self.community, "-t", "5", "-r", "1", "-Oqv", self.host, oid],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            raw = result.stdout.strip()
            if ": " in raw:
                raw = raw.split(": ", 1)[1]
            return raw.strip('"')
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log = getattr(self, "log", None)
            if log is not None:
                log.warning("snmp_get_failed", oid=oid, error=str(e))
            return None

    def _snmp_walk_sync(self, base_oid: str = "") -> dict[str, str]:
        """Synchronous SNMP walk via `snmpwalk`. Returns {oid: raw_value}. An
        empty base_oid walks from the root (full discovery)."""
        cmd = ["snmpwalk", "-v2c", "-c", self.community, "-t", "10", self.host]
        if base_oid:
            cmd.append(base_oid)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or not result.stdout.strip():
                return {}
            oids: dict[str, str] = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    parts = line.split("=", 1)
                    oids[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""
            return oids
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}

    @staticmethod
    def _parse_snmp_walk_value(raw: str | None) -> str:
        """Strip the SNMP type prefix + quotes from an snmpwalk value.

        snmpwalk emits `STRING: "x"`, `Gauge32: 123`, `Counter32: 0`, etc.;
        return just the value.
        """
        if raw is None:
            return ""
        s = str(raw).strip().strip('"')
        for prefix in (
            "STRING:",
            "Gauge32:",
            "Counter32:",
            "Counter64:",
            "INTEGER:",
            "Timeticks:",
            "Hex-STRING:",
            "OID:",
            "IpAddress:",
        ):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip().strip('"')
                break
        return s

    @staticmethod
    def _snmp_timeticks_to_hours(raw: str | None) -> float | None:
        """Convert an SNMP sysUpTime value to hours.

        Timeticks are hundredths of a second; the CLI renders them either as a
        bare number or as `(12345678) 3 days, 10:17:36`. Returns None if
        unparseable.
        """
        if raw is None:
            return None
        try:
            ticks = float(raw.split("(")[1].split(")")[0]) if "(" in raw else float(raw)
        except (ValueError, IndexError):
            return None
        return ticks / 360000.0
