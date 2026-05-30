"""
Aevus — Correlation Data Model
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from datetime import datetime


class Correlation(BaseModel):
    """A cross-domain correlation detected by the correlator engine."""

    id: str
    type: Literal["comm_degradation", "weather_rf_impact", "power_risk", "systemic_failure"]
    severity: Literal["critical", "warning", "info"]
    title: str
    description: str
    affected_assets: list[str]
    detected_at: datetime
