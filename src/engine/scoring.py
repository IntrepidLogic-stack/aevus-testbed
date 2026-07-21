"""
Aevus — shared 0-100 score → status banding.

One definition of how a numeric score becomes "good/warn/bad" so the platform's
scorers can't drift into three different meanings of the same words. Today
`health_score.health_status` (80/50), `pearl_score._band` (60/30), and
`normalizer.evaluate_status` each re-implement this comparison with different
cutoffs; see docs/ARCHITECTURE_REVIEW_2026-07.md (H2). Callers keep their own
cutoffs — only the banding logic is shared here.
"""

from __future__ import annotations

from typing import Literal

Status = Literal["good", "warn", "bad", "unknown"]


def band(
    score: float | None,
    warn_at: float,
    crit_at: float,
    *,
    zero_is_unknown: bool = False,
) -> Status:
    """Map a numeric score to a status string.

    Args:
        score: The value to band (higher = healthier).
        warn_at: `score >= warn_at` → "good".
        crit_at: `crit_at <= score < warn_at` → "warn"; below → "bad".
        zero_is_unknown: treat a score of exactly 0 as "unknown" (used by the
            health engine, where 0 means "never scored" rather than "critical").

    Returns:
        "good" | "warn" | "bad" | "unknown".
    """
    if score is None or (zero_is_unknown and score == 0):
        return "unknown"
    if score >= warn_at:
        return "good"
    if score >= crit_at:
        return "warn"
    return "bad"
