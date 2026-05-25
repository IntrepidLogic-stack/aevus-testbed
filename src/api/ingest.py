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


@router.post("")
async def ingest_vitals(payload: IngestPayload):
    """Accept vitals from a remote relay."""
    asset_id = payload.asset_id
    vitals = payload.vitals

    # Store latest data
    _relay_data[asset_id] = {
        "vitals": vitals,
        "timestamp": datetime.now(UTC).isoformat(),
        "relay": True,
    }

    logger.info("relay_ingest",
                asset_id=asset_id,
                vital_count=len(vitals),
                keys=list(vitals.keys())[:5])

    return {
        "status": "ok",
        "asset_id": asset_id,
        "vitals_ingested": len(vitals),
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
