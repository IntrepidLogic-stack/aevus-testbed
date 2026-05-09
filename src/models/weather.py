"""
Aevus — Weather Data Model
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WeatherData:
    """Current weather conditions at the site."""

    temp_f: float = 0.0
    wind_mph: float = 0.0
    wind_gust_mph: float = 0.0
    precip_in: float = 0.0
    condition: str = "unknown"
    sunrise: str = ""
    sunset: str = ""
    daylight_hours: float = 0.0
    is_daylight: bool = False
    solar_production_factor: float = 0.0
    fetched_at: datetime | None = None
