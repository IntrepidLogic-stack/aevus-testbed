"""
Aevus — Cross-Domain AI Correlation Engine
Combines field telemetry + network performance + weather for system-wide analysis.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.models.correlation import Correlation

if TYPE_CHECKING:
    from src.engine.comm_quality import CommQuality
    from src.models.asset import Asset
    from src.models.weather import WeatherData

logger = structlog.get_logger()


class CorrelationEngine:
    """Detects cross-domain correlations across field, network, and weather data."""

    def __init__(self) -> None:
        self._active: list[Correlation] = []
        self.log = logger.bind(component="correlator")

    @property
    def active_correlations(self) -> list[Correlation]:
        """Return currently active correlations."""
        return list(self._active)

    async def correlate(
        self,
        assets: list[Asset],
        weather: WeatherData | None,
        comm_quality: dict[str, CommQuality],
    ) -> list[Correlation]:
        """Run cross-domain correlation analysis.

        Detects patterns across field telemetry, network performance,
        and weather conditions.
        """
        now = datetime.now(UTC)
        correlations: list[Correlation] = []

        # ── Pattern 1: Communication Degradation ──
        degraded_assets = []
        for asset in assets:
            cq = comm_quality.get(asset.id)
            if cq and cq.quality_score < 70:
                degraded_assets.append(asset.id)

        if len(degraded_assets) >= 2:
            correlations.append(Correlation(
                id=f"COR-{uuid.uuid4().hex[:8].upper()}",
                type="comm_degradation",
                severity="warning",
                title="Multi-asset communication degradation",
                description=(
                    f"{len(degraded_assets)} assets showing degraded communication quality. "
                    f"Possible network infrastructure issue or RF interference."
                ),
                affected_assets=degraded_assets,
                detected_at=now,
            ))

        # ── Pattern 2: Weather → RF Impact ──
        if weather and weather.condition in (
            "rain", "heavy_rain", "thunderstorm", "thunderstorm_hail",
            "heavy_showers", "snow", "heavy_snow",
        ):
            radio_assets = [a.id for a in assets if a.type == "radio"]
            rf_degraded = [
                aid for aid in radio_assets
                if (cq := comm_quality.get(aid)) and cq.quality_score < 80
            ]
            if rf_degraded:
                correlations.append(Correlation(
                    id=f"COR-{uuid.uuid4().hex[:8].upper()}",
                    type="weather_rf_impact",
                    severity="warning",
                    title="Weather-related RF degradation",
                    description=(
                        f"Adverse weather ({weather.condition}) coinciding with "
                        f"RF performance degradation on {len(rf_degraded)} radio link(s). "
                        f"Wind: {weather.wind_mph} mph, Precip: {weather.precip_in} in."
                    ),
                    affected_assets=rf_degraded,
                    detected_at=now,
                ))

        # ── Pattern 3: Power Risk ──
        if weather:
            for asset in assets:
                if asset.type != "rtu":
                    continue
                # Check battery vitals
                battery_vital = None
                solar_vital = None
                for v in asset.vitals:
                    if v.label == "BATTERY":
                        battery_vital = v
                    if v.label == "SOLAR VOLTAGE":
                        solar_vital = v

                if battery_vital and battery_vital.status in ("warn", "bad"):
                    is_night_approaching = (
                        not weather.is_daylight
                        or weather.solar_production_factor < 0.2
                    )
                    if is_night_approaching or (
                        solar_vital and solar_vital.raw_value < 5.0
                    ):
                        correlations.append(Correlation(
                            id=f"COR-{uuid.uuid4().hex[:8].upper()}",
                            type="power_risk",
                            severity="critical" if battery_vital.status == "bad" else "warning",
                            title=f"Power loss risk: {asset.name}",
                            description=(
                                f"Battery at {battery_vital.value} with "
                                f"{'nighttime' if not weather.is_daylight else 'low solar'} "
                                f"conditions. Solar factor: {weather.solar_production_factor}. "
                                f"Daylight remaining: {'none' if not weather.is_daylight else 'limited'}."
                            ),
                            affected_assets=[asset.id],
                            detected_at=now,
                        ))

        # ── Pattern 4: Systemic Failure ──
        bad_assets = [a.id for a in assets if a.status == "bad"]
        if len(bad_assets) >= 3:
            correlations.append(Correlation(
                id=f"COR-{uuid.uuid4().hex[:8].upper()}",
                type="systemic_failure",
                severity="critical",
                title="Systemic infrastructure degradation",
                description=(
                    f"{len(bad_assets)} assets in critical state simultaneously. "
                    f"Possible site-wide issue (power, network backbone, environmental)."
                ),
                affected_assets=bad_assets,
                detected_at=now,
            ))

        self._active = correlations
        if correlations:
            self.log.info("correlations_detected", count=len(correlations))

        return correlations
