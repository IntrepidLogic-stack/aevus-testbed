"""
Aevus Testbed --- Asset API Routes
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from src.models.asset import Asset

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
async def list_assets(
    type: Optional[str] = Query(None, description="Filter by asset type"),
    status: Optional[str] = Query(None, description="Filter by status"),
) -> list[Asset]:
    """List all monitored assets with optional filters."""
    from src.main import app_state
    return app_state.db.list_assets(type_filter=type, status_filter=status)


@router.get("/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str) -> Asset:
    """Get a single asset by ID with full vitals and events."""
    from src.main import app_state
    asset = app_state.db.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset
