"""
Aevus API — in-process rate limiter for the paid AI endpoints.

The demo-referer bypass in src.api.auth intentionally lets unauthenticated
public visitors reach the /ai/* endpoints (that's the public demo). Those
endpoints call Bedrock, so without a throttle anyone can loop /ai/ask and run
up the model bill (ARCHITECTURE_REVIEW H3 follow-up). This is a per-client-IP
sliding-window limiter — no external store, no new dependency — sized so a human
operator never trips it while a scripted abuser trips it within seconds.

Limits come from settings at call time (not import) so they can be tuned via
.env without a code change and monkeypatched in tests:
    ai_rate_limit_requests        max requests per window per client (0 = off)
    ai_rate_limit_window_seconds  window length

It is deliberately NOT a security boundary — X-Forwarded-For is client-settable
and NAT shares IPs. It is a cost/abuse backstop. Authenticated high-volume
integrations that legitimately need more can raise the limit in config.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

import structlog
from fastapi import HTTPException, Request

from src.config import settings

logger = structlog.get_logger()


class SlidingWindowRateLimiter:
    """Thread-safe per-key sliding-window counter.

    Safe under FastAPI's threadpool: `check()` takes a short lock, prunes
    timestamps older than the window, and either records the hit or raises 429.
    Uses a monotonic clock so it is immune to wall-clock adjustments.
    """

    # Sweep fully-expired keys once the table grows past this, so a flood of
    # one-shot keys (e.g. random email addresses) cannot grow memory without bound.
    _SWEEP_THRESHOLD = 5000

    def __init__(
        self,
        limit_attr: str = "ai_rate_limit_requests",
        window_attr: str = "ai_rate_limit_window_seconds",
        detail: str = "AI request rate limit exceeded, slow down and retry shortly.",
        log_event: str = "ai_rate_limited",
    ) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._limit_attr = limit_attr
        self._window_attr = window_attr
        self._detail = detail
        self._log_event = log_event

    def _sweep(self, cutoff: float) -> None:
        """Drop keys whose newest hit is outside the window. Caller holds the lock."""
        for k in [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]:
            del self._hits[k]

    def check(self, key: str) -> None:
        """Record a hit for `key`; raise HTTPException(429) if over the limit."""
        limit = getattr(settings, self._limit_attr)
        window = getattr(settings, self._window_attr)
        if limit <= 0 or window <= 0:  # disabled (dev/test)
            return

        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            if len(self._hits) > self._SWEEP_THRESHOLD:
                self._sweep(cutoff)
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = int(dq[0] + window - now) + 1
                logger.warning(self._log_event, client=key, limit=limit, window=window)
                raise HTTPException(
                    status_code=429,
                    detail=self._detail,
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            dq.append(now)

    def reset(self) -> None:
        """Drop all recorded hits (test hook)."""
        with self._lock:
            self._hits.clear()


# Module-level singleton shared across requests.
ai_limiter = SlidingWindowRateLimiter()


def _client_key(request: Request) -> str:
    """Best-effort client identity for rate bucketing.

    Honors the first X-Forwarded-For hop when present (the app sits behind a
    proxy in prod), else the direct peer. Not trusted for auth — only bucketing.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


async def ai_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle a caller on the /ai/* router.

    Runs before the endpoint body, so a throttled request never reaches Bedrock.
    """
    ai_limiter.check(_client_key(request))
