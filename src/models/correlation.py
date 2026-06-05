"""
Aevus — Correlation Data Model
"""

from __future__ import annotations

from datetime import datetime  # runtime: Pydantic field type, needed for OpenAPI schema (#210)
from typing import Literal

from pydantic import BaseModel


class Correlation(BaseModel):
    """A cross-domain correlation detected by the correlator engine."""

    id: str
    type: Literal["comm_degradation", "weather_rf_impact", "power_risk", "systemic_failure"]
    severity: Literal["critical", "warning", "info"]
    title: str
    description: str
    affected_assets: list[str]
    detected_at: datetime
