"""
Aevus Testbed --- Asset API Routes
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from src.config import settings
from src.models.asset import Asset

router = APIRouter(prefix="/assets", tags=["assets"])
log = structlog.get_logger().bind(component="assets_api")


def _apply_read_source(assets: list[Asset]) -> list[Asset]:
    """Phase 2 convergence hook. Default (sqlite) = no-op, current behavior.

    dynamo : overlay each asset's live vitals/state from the DynamoDB
             latest-state store (registry stays the metadata source).
    dual   : leave the SQLite result untouched but log per-asset divergence
             vs what Dynamo would return — a zero-risk soak/validation mode.

    Any error degrades to the SQLite result + a logged warning; never raises.
    """
    src = settings.read_source
    if src not in ("dynamo", "dual"):
        return assets
    try:
        from src.storage.dynamo_latest_state import get_reader

        reader = get_reader()
        for a in assets:
            if src == "dynamo":
                reader.enrich(a)
            else:  # dual — observe only, return SQLite unchanged
                latest = reader.fetch(a.id)
                ddb_status = latest.state.get("status")
                ddb_fw = latest.state.get("firmware")
                if (ddb_status and ddb_status != a.status) or (ddb_fw and ddb_fw != a.firmware):
                    log.info(
                        "read_source_dual_divergence",
                        asset_id=a.id,
                        sqlite_status=a.status,
                        dynamo_status=ddb_status,
                        sqlite_fw=a.firmware,
                        dynamo_fw=ddb_fw,
                        dynamo_vitals=len(latest.vitals),
                    )
    except Exception as e:  # noqa: BLE001 — read-source overlay must never 500
        log.warning("read_source_apply_failed", source=src, error=str(e))
    return assets


@router.get("", response_model=list[Asset])
async def list_assets(
    type: str | None = Query(None, description="Filter by asset type"),
    status: str | None = Query(None, description="Filter by status"),
) -> list[Asset]:
    """List all monitored assets with optional filters."""
    from src.main import app_state

    assets = app_state.db.list_assets(type_filter=type, status_filter=status)
    from src.api.relay_overlay import apply_relay_overlay

    return apply_relay_overlay(_apply_read_source(assets))


@router.get("/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str) -> Asset:
    """Get a single asset by ID with full vitals and events."""
    from src.main import app_state

    asset = app_state.db.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    from src.api.relay_overlay import apply_relay_overlay

    return apply_relay_overlay(_apply_read_source([asset]))[0]


from pydantic import BaseModel as PydanticBaseModel


class GPSUpdate(PydanticBaseModel):
    latitude: float
    longitude: float


@router.put("/{asset_id}/gps")
async def update_asset_gps(asset_id: str, body: GPSUpdate):
    """Update GPS coordinates for an asset."""
    from src.main import app_state

    db = app_state.db
    db._conn.execute(
        "UPDATE assets SET latitude = ?, longitude = ? WHERE id = ?",
        (body.latitude, body.longitude, asset_id),
    )
    db._conn.commit()
    asset = db.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset
