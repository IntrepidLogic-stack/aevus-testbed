"""Flag-gated derived PROCESS-EQUIPMENT assets, built from live RTU telemetry.

OFF by default (settings.process_assets_enabled). When enabled, surfaces process
equipment assets whose vitals are pulled from the already-polling SCADAPack-470
(RTU-01) Modbus registers — the first *real* process-equipment binding for the
Killdeer twin (e.g. the CMP compressor, fed by the 470 compressor-group registers
that the modbus collector already reads).

Like ``reference_assets``, this NEVER touches the SQLite registry / seed and NEVER
raises into the endpoint (any error -> []), so it cannot break the live /assets
response or the seed (cf. the prior incidents where adding assets broke the seed
and the awards dashboard). It is a pure read-only overlay over RTU-01's vitals.

Trade-secret note: it emits only coarse engineering VitalSigns already permitted
on /assets — no raw process model, no pearl_score internals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.config import settings
from src.models.asset import Asset

if TYPE_CHECKING:
    from src.models.telemetry import VitalSign

log = structlog.get_logger().bind(component="process_assets")

_RTU_ID = "RTU-01"

# Compressor-group register labels (per src/engine/normalizer.py) that belong to
# the CMP equipment. Whatever subset RTU-01 currently exposes is bound; missing
# labels are simply skipped (best-effort, never raises).
_CMP_LABELS = (
    "SUCTION PRESSURE",
    "DISCHARGE PRESSURE",
    "GAS TEMP",
    "VIBRATION",
    "MOTOR CURRENT",
    "COMPRESSOR RPM",
    "INTERSTAGE TEMP",
    "OIL PRESSURE",
    "COOLANT TEMP",
    "RUN HOURS",
)


def _worst(vitals: list[VitalSign]) -> str:
    sv = {getattr(v, "status", "") for v in vitals}
    if "bad" in sv:
        return "bad"
    if "warn" in sv:
        return "warn"
    return "good" if vitals else "unknown"


def _cmp_from_rtu(rtu: Asset) -> Asset | None:
    """Derive the CMP compressor asset from RTU-01's compressor-group vitals."""
    comp = [v for v in (rtu.vitals or []) if v.label in _CMP_LABELS]
    if not comp:
        return None
    status = _worst(comp)
    health = {"bad": 35, "warn": 70, "good": 96}.get(status)
    return Asset(
        id="CMP",
        type="sensor",
        status=status,
        name="Field Sales Compressor",
        location="Killdeer / BlueJay #1 — compressor skid",
        health=health,
        last_seen=datetime.now(UTC),
        vendor="(field)",
        model="SCADAPack-470 derived (compressor group)",
        protocol="modbus",
        vitals=comp,
    )


def process_assets() -> list[Asset]:
    """Return derived process-equipment assets when enabled; [] otherwise / on error."""
    if not settings.process_assets_enabled:
        return []
    try:
        from src.main import app_state

        rtu = app_state.db.get_asset(_RTU_ID)
        if rtu is None:
            return []
        cmp_asset = _cmp_from_rtu(rtu)
        return [cmp_asset] if cmp_asset is not None else []
    except Exception as e:  # noqa: BLE001 — must never break /assets
        log.warning("process_assets_failed", error=str(e))
        return []
