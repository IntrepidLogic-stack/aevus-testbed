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

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record a hit for `key`; raise HTTPException(429) if over the limit."""
        limit = settings.ai_rate_limit_requests
        window = settings.ai_rate_limit_window_seconds
        if limit <= 0 or window <= 0:  # disabled (dev/test)
            return

        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = int(dq[0] + window - now) + 1
                logger.warning("ai_rate_limited", client=key, limit=limit, window=window)
                raise HTTPException(
                    status_code=429,
                    detail="AI request rate limit exceeded — slow down and retry shortly.",
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
