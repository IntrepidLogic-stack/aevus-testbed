"""Aevus API routes."""

from src.api.alerts import router as alerts_router
from src.api.assets import router as assets_router
from src.api.commands import router as commands_router
from src.api.correlations import router as correlations_router
from src.api.deploy import router as deploy_router
from src.api.diagnostics import router as diagnostics_router
from src.api.health import router as health_router
from src.api.integrations import router as integrations_router
from src.api.predictions import router as predictions_router
from src.api.reports import router as reports_router
from src.api.weather import router as weather_router
from src.api.ws import router as ws_router

__all__ = [
    "assets_router",
    "alerts_router",
    "commands_router",
    "correlations_router",
    "health_router",
    "deploy_router",
    "diagnostics_router",
    "predictions_router",
    "reports_router",
    "integrations_router",
    "weather_router",
    "ws_router",
]
