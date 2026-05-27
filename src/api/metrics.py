"""
Aevus Testbed --- Metrics API Routes

Exposes the latency histograms maintained by
src/integrations/latency_tracker. Drives the patent-demo metrics
view in the dashboard and provides the operator-facing evidence
for the P-008 latency claims.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.integrations import latency_tracker

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/latency")
async def latency_snapshot() -> dict:
    """Current rolling-window latency histograms.

    Returns:
      detection_latency_ms — DNP3 device_timestamp → received_at.
                             Proves Aevus catches the physical event
                             in milliseconds (P-008 detection latency).
      rca_latency_ms       — alert detected_at → RCA generated_at.
                             Proves the AI root cause arrives within
                             seconds (P-008 RCA latency).

    Each histogram has count, min, max, mean, p50, p95, p99 — all
    in milliseconds. p95 + p99 are the operator-relevant numbers;
    p50 is included for fast trend sanity-checks.
    """
    snap = latency_tracker.snapshot()
    return {
        "histograms": snap,
        "patent_demo_claims": {
            "p95_detection_target_ms": 500,
            "p95_rca_target_ms": 3000,
            "detection_within_target": snap["detection_latency_ms"]["p95_ms"] <= 500
            if snap["detection_latency_ms"]["count"] > 0
            else None,
            "rca_within_target": snap["rca_latency_ms"]["p95_ms"] <= 3000
            if snap["rca_latency_ms"]["count"] > 0
            else None,
        },
    }


@router.post("/latency/reset")
async def reset_latency_histograms() -> dict:
    """Clear both histograms. Useful between demo runs."""
    latency_tracker.reset_all()
    return {"status": "reset", "histograms": latency_tracker.snapshot()}
