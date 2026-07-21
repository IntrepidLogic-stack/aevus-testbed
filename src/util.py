"""
Aevus — small async utilities.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


async def run_blocking[T](fn: Callable[..., T], /, *args, **kwargs) -> T:
    """Run a blocking (synchronous) callable off the event loop, in a worker
    thread, and await its result.

    Use this for synchronous network/disk I/O invoked from an async path so a
    slow call can't stall every other coroutine. See
    docs/ARCHITECTURE_REVIEW_2026-07.md (H1) — the scheduler's poll cycle ran
    synchronous InfluxDB writes on the loop, so a slow Influx round-trip froze
    every asset's poll loop and the API at once.

    Thin wrapper over asyncio.to_thread so call sites read intentionally and we
    have one place to evolve the offload strategy (e.g. a bounded executor).
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
