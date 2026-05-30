"""
Aevus — Communication Quality Calculator
Computes % good communication metric for each asset.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class CommQuality:
    """Communication quality metrics for an asset."""

    asset_id: str
    success_rate: float = 100.0  # % successful polls
    error_rate: float = 0.0  # SNMP error rate %
    avg_response_ms: float = 0.0  # Average poll response time
    quality_score: float = 100.0  # Weighted composite 0-100


class CommQualityEngine:
    """Calculates communication quality scores for assets."""

    def __init__(self) -> None:
        self._scores: dict[str, CommQuality] = {}
        self.log = logger.bind(component="comm_quality")

    @property
    def scores(self) -> dict[str, CommQuality]:
        """All current quality scores."""
        return self._scores

    def get(self, asset_id: str) -> CommQuality | None:
        """Get comm quality for a specific asset."""
        return self._scores.get(asset_id)

    def calculate(
        self,
        asset_id: str,
        poll_count: int = 0,
        poll_success_count: int = 0,
        last_poll_duration_ms: float = 0.0,
        in_errors: int = 0,
        in_octets: int = 0,
    ) -> CommQuality:
        """Calculate communication quality for an asset.

        Args:
            asset_id: The asset to score.
            poll_count: Total polls attempted.
            poll_success_count: Successful polls.
            last_poll_duration_ms: Most recent poll duration in ms.
            in_errors: SNMP interface error count.
            in_octets: SNMP interface octet count.

        Returns:
            CommQuality with weighted composite score.
        """
        # Success rate
        success_rate = poll_success_count / poll_count * 100.0 if poll_count > 0 else 100.0

        # SNMP error rate
        total_io = in_octets + in_errors
        error_rate = in_errors / total_io * 100.0 if total_io > 0 else 0.0

        # Response time score (0-100, <50ms = 100, >2000ms = 0)
        if last_poll_duration_ms <= 50:
            response_score = 100.0
        elif last_poll_duration_ms >= 2000:
            response_score = 0.0
        else:
            response_score = 100.0 * (1.0 - (last_poll_duration_ms - 50) / 1950.0)

        # Weighted composite: 60% success + 30% error inverse + 10% response
        error_inverse = max(0.0, 100.0 - error_rate)
        quality_score = success_rate * 0.60 + error_inverse * 0.30 + response_score * 0.10
        quality_score = round(max(0.0, min(100.0, quality_score)), 1)

        cq = CommQuality(
            asset_id=asset_id,
            success_rate=round(success_rate, 1),
            error_rate=round(error_rate, 3),
            avg_response_ms=round(last_poll_duration_ms, 1),
            quality_score=quality_score,
        )

        self._scores[asset_id] = cq
        return cq
