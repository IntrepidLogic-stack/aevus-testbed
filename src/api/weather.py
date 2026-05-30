"""
Aevus — Weather API Router (with caching to avoid rate limits)
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import asdict

from fastapi import APIRouter

from src.config import settings

router = APIRouter(tags=["weather"])

# ── In-memory cache ──────────────────────────────────────────
_cache: dict[str, dict] = {}
CACHE_TTL_CURRENT = 300      # 5 min
CACHE_TTL_FORECAST = 1800    # 30 min


def _get_cached(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None


def _set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


@router.get("/weather")
async def get_weather():
    """Return current weather data for the site."""
    from src.main import app_state

    weather = app_state.weather_engine.current
    if weather is None:
        return {"status": "no_data", "message": "Weather data not yet available"}

    data = asdict(weather)
    if data.get("fetched_at"):
        data["fetched_at"] = data["fetched_at"].isoformat()
    return data


@router.get("/weather/forecast")
async def get_weather_forecast():
    """Return hourly (48h) and daily (7d) forecast — cached to avoid rate limits."""

    cached = _get_cached("forecast", CACHE_TTL_FORECAST)
    if cached:
        return cached

    lat = settings.site_latitude
    lon = settings.site_longitude
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,"
        f"precipitation_probability,precipitation,weather_code,"
        f"relative_humidity_2m,surface_pressure,visibility,"
        f"uv_index,cloud_cover,shortwave_radiation,direct_radiation"
        f"&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset,"
        f"precipitation_sum,precipitation_probability_max,"
        f"wind_speed_10m_max,wind_gusts_10m_max,weather_code,"
        f"uv_index_max,daylight_duration"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
        f"&precipitation_unit=inch"
        f"&timezone=America/Chicago"
        f"&forecast_days=7"
    )

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(url, timeout=15).read()  # noqa: S310 — trusted Open-Meteo https endpoint
        )
        data = json.loads(response)
        if not data.get("error"):
            _set_cached("forecast", data)
            import pathlib
            pathlib.Path("/home/ubuntu/aevus-testbed/forecast_cache.json").write_text(json.dumps(data))
        return data
    except Exception as e:
        # Return cached even if expired
        stale = _cache.get("forecast")
        if stale:
            return stale["data"]
        # Try disk cache
        import pathlib
        disk = pathlib.Path("/home/ubuntu/aevus-testbed/forecast_cache.json")
        if disk.exists():
            data = json.loads(disk.read_text())
            _set_cached("forecast", data)
            import pathlib
            pathlib.Path("/home/ubuntu/aevus-testbed/forecast_cache.json").write_text(json.dumps(data))
            return data
        return {"error": str(e)}
