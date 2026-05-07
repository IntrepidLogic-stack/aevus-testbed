"""
Aevus Testbed --- Predictions API Routes
Serves ML-powered failure predictions from the prediction engine.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.models.prediction import Prediction

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("")
async def list_predictions() -> list[dict]:
    """List predicted failures for all monitored assets.

    Returns predictions sorted by risk score (highest first).
    Each prediction includes risk score, estimated time-to-failure,
    confidence interval, and primary risk drivers.
    """
    from src.main import app_state

    preds = app_state.scheduler.prediction_engine.predictions
    return [p.model_dump() for p in preds]


@router.get("/{asset_id}")
async def get_prediction(asset_id: str) -> dict:
    """Get the prediction for a specific asset."""
    from src.main import app_state

    pred = app_state.scheduler.prediction_engine.get_prediction(asset_id)
    if pred is None:
        return {"asset_id": asset_id, "risk_score": 0, "message": "No prediction data available"}
    return pred.model_dump()
