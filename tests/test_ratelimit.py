"""Rate-limiter tests for the paid /ai/* endpoints (ARCHITECTURE_REVIEW H3).

Covers the limiter in isolation (allow N, block N+1, per-key isolation, window
expiry, disable switch) and that the FastAPI dependency raises 429 BEFORE the
endpoint body runs — i.e. a throttled caller never reaches Bedrock.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.ratelimit import SlidingWindowRateLimiter, _client_key, ai_limiter, ai_rate_limit
from src.config import settings


@pytest.fixture
def limits():
    """Pin a small, fast window and restore afterward."""
    orig = (settings.ai_rate_limit_requests, settings.ai_rate_limit_window_seconds)
    settings.ai_rate_limit_requests = 3
    settings.ai_rate_limit_window_seconds = 60
    yield
    settings.ai_rate_limit_requests, settings.ai_rate_limit_window_seconds = orig


def _req(ip="1.2.3.4", xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=ip))


class TestSlidingWindow:
    def test_allows_up_to_limit_then_blocks(self, limits):
        rl = SlidingWindowRateLimiter()
        for _ in range(3):
            rl.check("k")  # 3 allowed
        with pytest.raises(HTTPException) as ei:
            rl.check("k")  # 4th blocked
        assert ei.value.status_code == 429
        assert "Retry-After" in ei.value.headers

    def test_keys_are_isolated(self, limits):
        rl = SlidingWindowRateLimiter()
        for _ in range(3):
            rl.check("a")
        rl.check("b")  # different key unaffected

    def test_window_expiry_frees_budget(self, limits):
        settings.ai_rate_limit_window_seconds = 1
        rl = SlidingWindowRateLimiter()
        for _ in range(3):
            rl.check("k")
        with pytest.raises(HTTPException):
            rl.check("k")
        time.sleep(1.05)
        rl.check("k")  # window rolled over

    def test_disabled_when_limit_zero(self, limits):
        settings.ai_rate_limit_requests = 0
        rl = SlidingWindowRateLimiter()
        for _ in range(100):
            rl.check("k")  # never raises

    def test_reset_clears_state(self, limits):
        rl = SlidingWindowRateLimiter()
        for _ in range(3):
            rl.check("k")
        rl.reset()
        for _ in range(3):
            rl.check("k")  # budget restored


class TestClientKey:
    def test_prefers_first_forwarded_hop(self):
        assert _client_key(_req(ip="10.0.0.1", xff="8.8.8.8, 10.0.0.1")) == "8.8.8.8"

    def test_falls_back_to_peer(self):
        assert _client_key(_req(ip="10.0.0.1")) == "10.0.0.1"

    def test_missing_client(self):
        assert _client_key(SimpleNamespace(headers={}, client=None)) == "unknown"


class TestDependency:
    async def test_dependency_raises_429_over_limit(self, limits):
        ai_limiter.reset()
        r = _req(ip="9.9.9.9")
        for _ in range(3):
            await ai_rate_limit(r)
        with pytest.raises(HTTPException) as ei:
            await ai_rate_limit(r)
        assert ei.value.status_code == 429
        ai_limiter.reset()
