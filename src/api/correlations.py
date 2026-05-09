"""
Aevus — Correlations API Router
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["correlations"])


@router.get("/correlations")
async def get_correlations():
    """Return active cross-domain correlations."""
    from src.main import app_state

    correlations = app_state.correlator.active_correlations
    return [c.model_dump(mode="json") for c in correlations]
