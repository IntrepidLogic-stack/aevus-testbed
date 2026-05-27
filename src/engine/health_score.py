"""
Aevus Testbed --- Composite Health Score Engine
Computes a 0-100 health score for each asset based on its vitals.

Weights:
  - Communication reliability: 35%  (is the device responding on time?)
  - Vital-sign compliance: 30%      (are readings within normal ranges?)
  - Predictive risk inversion: 20%  (inverse of predicted failure risk)
  - Maintenance currency: 15%       (firmware age, run hours, etc.)

Status assignment:
  80-100 -> good
  50-79  -> warn
  1-49   -> bad
  0/None -> unknown
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import structlog

from src.models.telemetry import VitalSign

logger = structlog.get_logger()

# How long without a poll before we start penalizing
STALE_WARN_SECONDS = 120  # 2 minutes
STALE_CRIT_SECONDS = 600  # 10 minutes


def _comm_score(last_seen: datetime | None, poll_interval: int) -> float:
    """Score communication reliability 0-100.

    Full marks if last_seen is within 2x poll_interval.
    Degrades linearly to 0 at STALE_CRIT_SECONDS.
    """
    if last_seen is None:
        return 0.0

    age = (datetime.now(UTC) - last_seen).total_seconds()
    fresh_limit = poll_interval * 2.0

    if age <= fresh_limit:
        return 100.0
    if age >= STALE_CRIT_SECONDS:
        return 0.0

    # Linear decay from 100 -> 0 between fresh_limit and STALE_CRIT
    return max(0.0, 100.0 * (1.0 - (age - fresh_limit) / (STALE_CRIT_SECONDS - fresh_limit)))


def _vital_compliance_score(vitals: list[VitalSign]) -> float:
    """Score vital-sign compliance 0-100.

    Each vital with a status contributes equally.
    good = 100, warn = 50, bad = 0, "" (info) = excluded.
    """
    scored = [(v.status, v) for v in vitals if v.status in ("good", "warn", "bad")]
    if not scored:
        return 100.0  # No threshold-monitored vitals = assume OK

    status_points = {"good": 100.0, "warn": 50.0, "bad": 0.0}
    total = sum(status_points[s] for s, _ in scored)
    return total / len(scored)


def _predictive_risk_score(risk_score: int | None) -> float:
    """Invert a 0-100 risk score so low risk = high health.

    If no prediction exists, assume moderate (70/100).
    """
    if risk_score is None:
        return 70.0
    return max(0.0, min(100.0, 100.0 - risk_score))


def _maintenance_score(
    firmware: str | None = None,
    run_hours: float | None = None,
) -> float:
    """Score maintenance currency 0-100.

    Placeholder: returns 80 (decent) by default.
    Deducts points for very high run hours.
    Future: compare firmware version against known-good.
    """
    score = 80.0

    if run_hours is not None:
        if run_hours > 50000:
            score -= 30.0
        elif run_hours > 20000:
            score -= 15.0
        elif run_hours > 10000:
            score -= 5.0

    return max(0.0, score)


def compute_health(
    vitals: list[VitalSign],
    last_seen: datetime | None = None,
    poll_interval: int = 30,
    risk_score: int | None = None,
    firmware: str | None = None,
    run_hours: float | None = None,
) -> int:
    """Compute composite health score 0-100.

    Args:
        vitals: Current VitalSign readings for the asset.
        last_seen: Timestamp of last successful poll.
        poll_interval: Expected poll interval in seconds.
        risk_score: Predicted failure risk 0-100 (from prediction engine).
        firmware: Current firmware version string.
        run_hours: Total equipment run hours.

    Returns:
        Integer health score 0-100.
    """
    comm = _comm_score(last_seen, poll_interval)
    compliance = _vital_compliance_score(vitals)
    predictive = _predictive_risk_score(risk_score)
    maintenance = _maintenance_score(firmware, run_hours)

    weighted = comm * 0.35 + compliance * 0.30 + predictive * 0.20 + maintenance * 0.15

    score = int(round(max(0.0, min(100.0, weighted))))

    logger.debug(
        "health_computed",
        comm=round(comm, 1),
        compliance=round(compliance, 1),
        predictive=round(predictive, 1),
        maintenance=round(maintenance, 1),
        final=score,
    )

    return score


def health_status(score: int | None) -> Literal["good", "warn", "bad", "unknown"]:
    """Map a health score to a status string."""
    if score is None or score == 0:
        return "unknown"
    if score >= 80:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"
