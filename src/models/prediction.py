"""
Aevus Testbed — Prediction Data Model
"""

from pydantic import BaseModel


class Prediction(BaseModel):
    """A predicted failure from the ML engine."""

    asset_id: str
    asset_name: str
    asset_type: str
    location: str
    risk_score: int             # 0-100
    estimated_failure: str      # "3 days"
    confidence_interval: str    # "2-5 days"
    primary_drivers: list[str]  # ["SNR degradation", "error rate increase"]
