"""
Aevus — Weather + Daylight Integration Engine
Uses Open-Meteo API (free, no key needed) and solar position calculation.
"""
from __future__ import annotations

import json
import math
import pathlib
from datetime import UTC, datetime, timezone, timedelta

import structlog

from src.config import settings
from src.models.weather import WeatherData

logger = structlog.get_logger()

CACHE_PATH = pathlib.Path("/home/ubuntu/aevus-testbed/weather_cache.json")

# WMO weather codes to human-readable conditions
WMO_CODES: dict[int, str] = {
    0: "clear", 1: "mostly_clear", 2: "partly_cloudy", 3: "overcast",
    45: "fog", 48: "fog", 51: "drizzle", 53: "drizzle", 55: "drizzle",
    61: "rain", 63: "rain", 65: "heavy_rain", 71: "snow", 73: "snow",
    75: "heavy_snow", 77: "ice", 80: "showers", 81: "showers", 82: "heavy_showers",
    85: "snow_showers", 86: "snow_showers", 95: "thunderstorm",
    96: "thunderstorm_hail", 99: "thunderstorm_hail",
}

WEATHER_SOLAR_FACTOR: dict[str, float] = {
    "clear": 1.0, "mostly_clear": 0.9, "partly_cloudy": 0.7,
    "overcast": 0.5, "fog": 0.4, "drizzle": 0.3, "rain": 0.2,
    "heavy_rain": 0.1, "snow": 0.15, "heavy_snow": 0.05,
    "showers": 0.2, "heavy_showers": 0.1, "ice": 0.1,
    "snow_showers": 0.15, "thunderstorm": 0.05,
    "thunderstorm_hail": 0.02, "unknown": 0.5,
}

COMPASS_DIRS = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
                "S","SSW","SW","WSW","W","WNW","NW","NNW"]


def _solar_declination(day_of_year: int) -> float:
    return math.radians(23.45) * math.sin(math.radians(360 / 365 * (day_of_year - 81)))


def _hour_angle_sunrise(lat_rad: float, decl: float) -> float:
    cos_ha = -math.tan(lat_rad) * math.tan(decl)
    if cos_ha < -1:
        return math.pi
    if cos_ha > 1:
        return 0.0
    return math.acos(cos_ha)


def _calculate_sunrise_sunset(lat: float, lon: float, now: datetime):
    doy = now.timetuple().tm_yday
    lat_rad = math.radians(lat)
    decl = _solar_declination(doy)
    ha_sunrise = _hour_angle_sunrise(lat_rad, decl)
    solar_noon_utc = 12.0 - (lon / 15.0)
    daylight_hours = 2.0 * math.degrees(ha_sunrise) / 15.0
    half_day = daylight_hours / 2.0
    base = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
    sunrise_dt = base + timedelta(hours=solar_noon_utc - half_day)
    sunset_dt = base + timedelta(hours=solar_noon_utc + half_day)
    return sunrise_dt, sunset_dt, daylight_hours


def _solar_factor_time(now: datetime, sunrise: datetime, sunset: datetime) -> float:
    if now <= sunrise or now >= sunset:
        return 0.0
    total = (sunset - sunrise).total_seconds()
    elapsed = (now - sunrise).total_seconds()
    return math.sin(math.pi * elapsed / total)


class WeatherEngine:
    """Fetches weather data and calculates solar production factors."""

    def __init__(self) -> None:
        self._current: WeatherData | None = None
        self.log = logger.bind(component="weather")
        self._load_seed()

    def _load_seed(self) -> None:
        """Load cached weather from disk (survives API rate limits)."""
        if CACHE_PATH.exists():
            try:
                d = json.loads(CACHE_PATH.read_text())
                self._current = WeatherData(
                    temp_f=d.get("temp_f", 0),
                    wind_mph=d.get("wind_mph", 0),
                    wind_gust_mph=d.get("wind_gust_mph", 0),
                    precip_in=d.get("precip_in", 0),
                    condition=d.get("condition", "unknown"),
                    sunrise=d.get("sunrise", ""),
                    sunset=d.get("sunset", ""),
                    daylight_hours=d.get("daylight_hours", 0),
                    is_daylight=d.get("is_daylight", True),
                    solar_production_factor=d.get("solar_production_factor", 0),
                    cloud_cover=d.get("cloud_cover", 50),
                    wind_dir=d.get("wind_dir", ""),
                    fetched_at=datetime.now(UTC),
                )
                self.log.info("weather_seed_loaded")
            except Exception as e:
                self.log.warning("weather_seed_failed", error=str(e))

    @property
    def current(self) -> WeatherData | None:
        return self._current

    def _save_cache(self, w: WeatherData) -> None:
        """Persist current weather to disk."""
        try:
            CACHE_PATH.write_text(json.dumps({
                "temp_f": w.temp_f, "wind_mph": w.wind_mph,
                "wind_gust_mph": w.wind_gust_mph, "precip_in": w.precip_in,
                "condition": w.condition, "sunrise": w.sunrise,
                "sunset": w.sunset, "daylight_hours": w.daylight_hours,
                "is_daylight": w.is_daylight,
                "solar_production_factor": w.solar_production_factor,
                "cloud_cover": w.cloud_cover, "wind_dir": w.wind_dir,
            }))
        except Exception:
            pass

    async def poll(self) -> WeatherData:
        """Fetch current weather from Open-Meteo and compute solar factors."""
        import urllib.request
        import asyncio

        lat = settings.site_latitude
        lon = settings.site_longitude
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,wind_speed_10m,wind_gusts_10m,"
            f"wind_direction_10m,cloud_cover,precipitation,weather_code"
        )

        now = datetime.now(UTC)
        sunrise, sunset, daylight_hours = _calculate_sunrise_sunset(lat, lon, now)
        is_daylight = sunrise <= now <= sunset

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(url, timeout=10).read()
            )
            data = json.loads(response)

            if data.get("error"):
                raise Exception(data.get("reason", "API error"))

            current = data.get("current", {})
            temp_c = current.get("temperature_2m", 0.0)
            temp_f = temp_c * 9.0 / 5.0 + 32.0
            wind_kmh = current.get("wind_speed_10m", 0.0)
            wind_mph = wind_kmh * 0.621371
            gust_kmh = current.get("wind_gusts_10m", 0.0)
            gust_mph = gust_kmh * 0.621371
            precip_mm = current.get("precipitation", 0.0)
            precip_in = precip_mm / 25.4
            weather_code = current.get("weather_code", 0)
            cloud_cover = current.get("cloud_cover", 50)
            wind_dir_deg = current.get("wind_direction_10m", 0)
            wind_dir = COMPASS_DIRS[int((wind_dir_deg + 11.25) / 22.5) % 16]
            condition = WMO_CODES.get(weather_code, "unknown")

        except Exception as e:
            self.log.error("weather_fetch_failed", error=str(e))
            if self._current is not None:
                self.log.info("weather_using_cached",
                              age_s=round((now - self._current.fetched_at).total_seconds()))
                return self._current
            condition = "unknown"
            temp_f = 0.0
            wind_mph = 0.0
            gust_mph = 0.0
            precip_in = 0.0
            cloud_cover = 50
            wind_dir = ""

        time_factor = _solar_factor_time(now, sunrise, sunset)
        weather_factor = WEATHER_SOLAR_FACTOR.get(condition, 0.5)
        solar_production_factor = round(time_factor * weather_factor, 3)

        weather = WeatherData(
            temp_f=round(temp_f, 1),
            wind_mph=round(wind_mph, 1),
            wind_gust_mph=round(gust_mph, 1),
            precip_in=round(precip_in, 3),
            condition=condition,
            sunrise=sunrise.strftime("%H:%M UTC"),
            sunset=sunset.strftime("%H:%M UTC"),
            daylight_hours=round(daylight_hours, 2),
            is_daylight=is_daylight,
            solar_production_factor=solar_production_factor,
            cloud_cover=cloud_cover,
            wind_dir=wind_dir,
            fetched_at=now,
        )

        self._current = weather
        self._save_cache(weather)
        self.log.info("weather_updated",
                      temp_f=weather.temp_f, condition=condition,
                      solar_factor=solar_production_factor)
        return weather
