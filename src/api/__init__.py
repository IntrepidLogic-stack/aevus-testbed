"""Aevus API routes."""

from src.api.assets import router as assets_router
from src.api.alerts import router as alerts_router
from src.api.health import router as health_router
from src.api.diagnostics import router as diagnostics_router
from src.api.metrics import router as metrics_router
from src.api.predictions import router as predictions_router
from src.api.ws import router as ws_router

__all__ = [
    "assets_router",
    "alerts_router",
    "health_router",
    "diagnostics_router",
    "metrics_router",
    "predictions_router",
    "ws_router",
]
