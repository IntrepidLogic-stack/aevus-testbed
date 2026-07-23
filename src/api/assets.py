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


def _apply_poll_evidence(assets: list[Asset]) -> list[Asset]:
    """Overlay live poll-cycle evidence from the running collectors
    (P3 contract #2). Serve-time only, never persisted, never raises."""
    try:
        from src.main import app_state
        from src.models.asset import PollEvidence

        for a in assets:
            stats = app_state.scheduler.poll_evidence(a.id)
            if stats is not None:
                a.poll = PollEvidence(**stats)
    except Exception as e:  # noqa: BLE001 — evidence overlay must never 500
        log.warning("poll_evidence_apply_failed", error=str(e))
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

    result = apply_relay_overlay(_apply_read_source(assets))

    # Flag-gated REFERENCE assets (real recorded datasets) — OFF by default; appended
    # in-memory, never via the registry, and never able to raise (see reference_assets).
    from src.api.reference_assets import reference_assets

    refs = reference_assets()
    if type:
        refs = [a for a in refs if a.type == type]
    if status:
        refs = [a for a in refs if a.status == status]

    # Flag-gated derived PROCESS assets (e.g. CMP from the live SCADAPack-470) — OFF by
    # default; appended in-memory, never via the registry, and never able to raise.
    from src.api.process_assets import process_assets

    procs = process_assets()
    if type:
        procs = [a for a in procs if a.type == type]
    if status:
        procs = [a for a in procs if a.status == status]

    # Flag-gated read-only OPC UA "Sidecar" overlay — OFF by default; in-memory only,
    # never via the registry, and never able to raise (see opcua_assets).
    from src.api.opcua_assets import opcua_assets

    opcua = opcua_assets()
    if type:
        opcua = [a for a in opcua if a.type == type]
    if status:
        opcua = [a for a in opcua if a.status == status]
    return _apply_poll_evidence(result + refs + procs + opcua)


@router.get("/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str) -> Asset:
    """Get a single asset by ID with full vitals and events."""
    from src.main import app_state

    asset = app_state.db.get_asset(asset_id)
    if asset is None:
        from src.api.reference_assets import reference_assets

        ref = next((a for a in reference_assets() if a.id == asset_id), None)
        if ref is not None:
            return ref
        from src.api.process_assets import process_assets

        proc = next((a for a in process_assets() if a.id == asset_id), None)
        if proc is not None:
            return proc
        from src.api.opcua_assets import opcua_assets

        opcua = next((a for a in opcua_assets() if a.id == asset_id), None)
        if opcua is not None:
            return opcua
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    from src.api.relay_overlay import apply_relay_overlay

    return _apply_poll_evidence(apply_relay_overlay(_apply_read_source([asset])))[0]


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
