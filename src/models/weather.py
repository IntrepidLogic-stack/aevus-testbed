"""
Aevus — Weather Data Model
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    cloud_cover: float = 50.0
    wind_dir: str = ""
    ghi: float = 0.0  # Global Horizontal Irradiance W/m2
    dni: float = 0.0  # Direct Normal Irradiance W/m2
    fetched_at: datetime | None = None
