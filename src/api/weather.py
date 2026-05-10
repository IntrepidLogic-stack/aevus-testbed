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


@router.get("/weather/forecast")
async def get_weather_forecast():
    """Return hourly (48h) and daily (7d) forecast for the site."""
    import asyncio
    import json
    import urllib.request
    from src.config import settings

    lat = settings.site_latitude
    lon = settings.site_longitude
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,"
        f"precipitation_probability,precipitation,weather_code,"
        f"relative_humidity_2m,surface_pressure,visibility,"
        f"uv_index,cloud_cover"
        f"&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset,"
        f"precipitation_sum,precipitation_probability_max,"
        f"wind_speed_10m_max,wind_gusts_10m_max,weather_code,"
        f"uv_index_max"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
        f"&precipitation_unit=inch"
        f"&timezone=America/Chicago"
        f"&forecast_days=7"
    )

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(url, timeout=15).read()
        )
        data = json.loads(response)
        return data
    except Exception as e:
        return {"error": str(e)}
