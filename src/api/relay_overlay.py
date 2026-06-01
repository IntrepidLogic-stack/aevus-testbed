"""Relay overlay — surface /ingest relay vitals onto registry assets.

═══════════════════════════════════════════════════════════════════════════
THE GAP THIS CLOSES
═══════════════════════════════════════════════════════════════════════════
`/api/v1/ingest` stores pushed vitals in `ingest._relay_data` (in-memory) and
best-effort into InfluxDB. But the asset read path — `/api/v1/assets` AND the
Rickerson pearl chain (`pearls.killdeer_pearls`) — reads ONLY from the SQLite
registry. So a remote relay (e.g. the SHOP-01 PowerShell relay polling the
SCADAPack 470 over Modbus TCP at 172.16.1.200, which only SHOP-01 can reach)
had nowhere for its data to surface. This module is the missing consumer.

═══════════════════════════════════════════════════════════════════════════
DESIGN RULES (so the live show-back demo is never at risk)
═══════════════════════════════════════════════════════════════════════════
  1. ADDITIVE + FRESHNESS-GATED. If no *fresh* relay data exists for an asset,
     that asset is returned untouched — byte-identical to pre-overlay behavior.
     With no relay running, NOTHING changes. The simulator demo is unaffected.
  2. NEVER RAISES. Any error degrades to the original asset list + a logged
     warning. The dashboard must never 500 because of an overlay.
  3. REAL REPLACES SIM. When fresh relay data exists for an asset, it replaces
     that asset's vitals and marks source="relay", so the pearl scores real
     telemetry and the resolver can prefer a real-sourced asset over a sim.
  4. HONEST. The relay sends only what it can actually measure (Modbus comms
     health: link + latency). It does NOT fabricate a battery voltage — so
     score_rtu computes a truthful "RTU reachable, comms healthy" score
     instead of a fake "battery good".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.models.telemetry import VitalSign

if TYPE_CHECKING:
    from src.models.asset import Asset

log = structlog.get_logger().bind(component="relay_overlay")

# Relay data older than this (seconds) is stale → ignored, fall back to the
# registry/simulator. Generous multiple of the relay's poll cadence (~30 s).
RELAY_FRESH_SECONDS = 180

# Real (non-simulator) vital sources, used to decide resolver preference.
REAL_SOURCES = {"relay", "modbus", "dnp3", "snmp"}


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _is_fresh(ts: str | None, now: datetime) -> bool:
    parsed = _parse_ts(ts)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (now - parsed).total_seconds() <= RELAY_FRESH_SECONDS


def _vital_from_entry(label: str, raw: object) -> VitalSign | None:
    """Build a VitalSign from one relay vitals entry.

    Accepts either a bare number ``{"MODBUS LATENCY": 8}`` or a dict
    ``{"MODBUS LATENCY": {"value": 8, "unit": "ms", "status": "good"}}``.
    Non-numeric string vitals (e.g. an alarm flagged "ACTIVE") are preserved
    with raw_value 0.0 so score_rtu's alarm scan still sees them.
    """
    label = str(label).strip().upper()
    unit = ""
    status = ""
    value_str: str
    raw_value: float

    if isinstance(raw, bool):
        # bool is an int subclass; treat explicitly
        raw_value = 1.0 if raw else 0.0
        value_str = str(int(raw_value))
    elif isinstance(raw, int | float):
        raw_value = float(raw)
        value_str = f"{raw_value:g}"
    elif isinstance(raw, dict):
        v = raw.get("value")
        unit = str(raw.get("unit", ""))
        status = str(raw.get("status", ""))
        if isinstance(v, bool):
            raw_value = 1.0 if v else 0.0
            value_str = str(int(raw_value))
        elif isinstance(v, int | float):
            raw_value = float(v)
            value_str = f"{raw_value:g}{(' ' + unit) if unit else ''}".strip()
        else:
            # string value (e.g. an alarm state "ACTIVE")
            raw_value = 0.0
            value_str = str(v) if v is not None else ""
    else:
        # bare string (e.g. "ACTIVE")
        raw_value = 0.0
        value_str = str(raw)

    return VitalSign(
        label=label,
        value=value_str,
        raw_value=raw_value,
        unit=unit,
        status=status,
        group="",
        source="relay",
    )


def _status_from_vitals(vitals: list[VitalSign]) -> str:
    """Derive a coarse asset status from relay vitals so score_rtu doesn't
    short-circuit on status=='offline'. Comms-link down or an ACTIVE alarm
    pulls it to warn/bad; otherwise good."""
    link_down = any(v.label in ("MODBUS LINK", "LINK STATE") and v.raw_value < 1 for v in vitals)
    active_alarm = any("ALARM" in v.label and str(v.value).upper() == "ACTIVE" for v in vitals)
    if link_down:
        return "bad"
    if active_alarm:
        return "warn"
    return "good"


def apply_relay_overlay(assets: list[Asset]) -> list[Asset]:
    """Overlay fresh /ingest relay vitals onto matching registry assets.

    Returns the same list (assets mutated in place when overlaid). Never
    raises — any failure logs a warning and leaves assets untouched.
    """
    try:
        from src.api.ingest import get_relay_data

        relay = get_relay_data()
        if not relay:
            return assets
        now = datetime.now(UTC)
        for a in assets:
            entry = relay.get(a.id)
            if not entry or not _is_fresh(entry.get("timestamp"), now):
                continue
            vitals_dict = entry.get("vitals") or {}
            new_vitals: list[VitalSign] = []
            for label, raw in vitals_dict.items():
                vs = _vital_from_entry(label, raw)
                if vs is not None:
                    new_vitals.append(vs)
            if not new_vitals:
                continue
            a.vitals = new_vitals
            a.status = _status_from_vitals(new_vitals)
            a.protocol = "modbus" if a.type == "rtu" else a.protocol
            ts = _parse_ts(entry.get("timestamp"))
            if ts is not None:
                a.last_seen = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
            log.info("relay_overlay_applied", asset_id=a.id, vitals=len(new_vitals), status=a.status)
    except Exception as e:  # noqa: BLE001 — overlay must never break the read path
        log.warning("relay_overlay_failed", error=str(e))
    return assets


def is_real_sourced(asset: Asset) -> bool:
    """True if any of the asset's vitals come from a real (non-simulator)
    source. Used by the pearl resolver to prefer a live SCADAPack over the
    seeded simulator when both satisfy a pearl slot."""
    return any((v.source or "") in REAL_SOURCES for v in (asset.vitals or []))
