"""
Aevus — Remote Ingest API
Accepts vitals from remote relay collectors (e.g., shop PC polling SCADAPack via USB).
Injects data into the same pipeline as local collectors.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter(prefix="/ingest", tags=["ingest"])

# In-memory store for latest relay data (accessed by assets API)
_relay_data: dict[str, dict] = {}


class IngestPayload(BaseModel):
    asset_id: str
    vitals: dict


def get_relay_data() -> dict[str, dict]:
    return _relay_data


def _persist_to_historian(asset_id: str, vitals: dict) -> int:
    """Best-effort write of ingested vitals to InfluxDB so the historian
    (/api/v1/health/trend) has data for edge-pushed assets.

    HISTORIAN GAP FIX (Task #196): before this, /ingest stored vitals in
    the in-memory _relay_data dict ONLY — the dashboard showed live values
    but the TRENDS button always reported 'no historian samples yet'
    because nothing reached InfluxDB on the edge-push path. Only the EC2
    scheduler's direct SNMP polling wrote to Influx, and that path can't
    reach the lab LAN from AWS.

    This is wrapped in a broad try/except and returns 0 on any failure:
    the live ingest response must NEVER break because of a historian write
    (influx down, unexpected vitals shape, etc). Telemetry persistence is
    a nice-to-have; the live dashboard is the must-have.

    Accepts both vitals shapes the edge may send:
      {metric: number}                      → value, unit=""
      {metric: {"value": n, "unit": "..."}} → value, unit
    """
    try:
        from src.main import app_state
        from src.models.telemetry import RawTelemetry

        influx = getattr(app_state, "influx", None)
        if influx is None:
            return 0

        now = datetime.now(UTC)
        readings: list[RawTelemetry] = []
        for metric, raw in (vitals or {}).items():
            value = None
            unit = ""
            if isinstance(raw, int | float):
                value = float(raw)
            elif isinstance(raw, dict):
                v = raw.get("value", raw.get("raw_value"))
                if isinstance(v, int | float):
                    value = float(v)
                    unit = str(raw.get("unit", ""))
            if value is None:
                continue  # skip non-numeric vitals (strings like "LINKED")
            readings.append(
                RawTelemetry(
                    asset_id=asset_id,
                    metric=str(metric).lower().replace(" ", "_"),
                    value=value,
                    unit=unit,
                    timestamp=now,
                    source="relay",
                )
            )
        if readings:
            influx.write_readings(readings)
        return len(readings)
    except Exception as e:  # noqa: BLE001 — best-effort, never break live ingest
        logger.warning("ingest_historian_write_failed", asset_id=asset_id, error=str(e))
        return 0


@router.post("")
async def ingest_vitals(payload: IngestPayload):
    """Accept vitals from a remote relay."""
    asset_id = payload.asset_id
    vitals = payload.vitals

    # Store latest data (live dashboard source)
    _relay_data[asset_id] = {
        "vitals": vitals,
        "timestamp": datetime.now(UTC).isoformat(),
        "relay": True,
    }

    # Persist to historian (best-effort — never breaks the live response)
    historian_count = _persist_to_historian(asset_id, vitals)

    logger.info(
        "relay_ingest",
        asset_id=asset_id,
        vital_count=len(vitals),
        historian_written=historian_count,
        keys=list(vitals.keys())[:5],
    )

    return {
        "status": "ok",
        "asset_id": asset_id,
        "vitals_ingested": len(vitals),
        "historian_written": historian_count,
        "timestamp": time.time(),
    }


@router.get("/status")
async def relay_status():
    """Show status of all relay-connected assets."""
    result = {}
    for asset_id, data in _relay_data.items():
        result[asset_id] = {
            "vital_count": len(data.get("vitals", {})),
            "last_update": data.get("timestamp"),
            "relay": True,
        }
    return result
