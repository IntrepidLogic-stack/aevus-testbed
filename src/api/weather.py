"""
Aevus — Weather API Router
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

router = APIRouter(tags=["weather"])


@router.get("/weather")
async def get_weather():
    """Return current weather data for the site."""
    from src.main import app_state

    weather = app_state.weather_engine.current
    if weather is None:
        return {"status": "no_data", "message": "Weather data not yet available"}

    data = asdict(weather)
    # Convert datetime to ISO string for JSON
    if data.get("fetched_at"):
        data["fetched_at"] = data["fetched_at"].isoformat()
    return data
