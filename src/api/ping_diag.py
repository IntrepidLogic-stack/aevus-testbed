"""
Aevus — Continuous Ping Diagnostic Tool
Configurable ping with real-time results, inspired by OneSCADA CI.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/diagnostics/ping", tags=["diagnostics"])

# Store ping results in memory (last 1000 per target)
_ping_results: dict[str, list[dict]] = {}
_active_pings: dict[str, bool] = {}


class PingRequest(BaseModel):
    target: str
    count: int = 20
    interval: float = 1.0  # seconds between pings
    packet_size: int = 56
    timeout: float = 5.0


class PingResult(BaseModel):
    target: str
    seq: int
    rtt_ms: float | None  # None = timeout
    ttl: int | None
    timestamp: str
    packet_size: int


async def _run_ping(target: str, count: int, interval: float, packet_size: int, timeout: float):
    """Run ping in background and store results."""
    _active_pings[target] = True
    if target not in _ping_results:
        _ping_results[target] = []

    for seq in range(1, count + 1):
        if not _active_pings.get(target, False):
            break

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(int(timeout)),
                "-s", str(packet_size), target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
            (time.monotonic() - start) * 1000
            output = stdout.decode()

            # Parse RTT from ping output
            rtt_match = re.search(r"time[=<](\d+\.?\d*)", output)
            ttl_match = re.search(r"ttl=(\d+)", output)

            rtt = float(rtt_match.group(1)) if rtt_match else None
            ttl = int(ttl_match.group(1)) if ttl_match else None

            if proc.returncode != 0:
                rtt = None
                ttl = None
        except (TimeoutError, Exception):
            rtt = None
            ttl = None

        result = {
            "target": target,
            "seq": seq,
            "rtt_ms": rtt,
            "ttl": ttl,
            "timestamp": datetime.now(UTC).isoformat(),
            "packet_size": packet_size,
            "timeout": rtt is None,
        }
        _ping_results[target].append(result)
        # Keep last 1000
        if len(_ping_results[target]) > 1000:
            _ping_results[target] = _ping_results[target][-1000:]

        if seq < count:
            await asyncio.sleep(interval)

    _active_pings[target] = False


@router.post("/start")
async def start_ping(req: PingRequest):
    """Start a continuous ping to a target."""
    if _active_pings.get(req.target, False):
        return {"status": "already_running", "target": req.target}

    # Clear old results
    _ping_results[req.target] = []

    # Start in background
    asyncio.create_task(_run_ping(
        req.target, req.count, req.interval, req.packet_size, req.timeout
    ))

    return {"status": "started", "target": req.target, "count": req.count, "interval": req.interval}


@router.post("/stop")
async def stop_ping(target: str):
    """Stop an active ping."""
    if target in _active_pings:
        _active_pings[target] = False
    return {"status": "stopped", "target": target}


@router.get("/results")
async def get_results(target: str, since_seq: int = 0):
    """Get ping results, optionally since a sequence number (for polling)."""
    results = _ping_results.get(target, [])
    if since_seq > 0:
        results = [r for r in results if r["seq"] > since_seq]

    # Compute stats
    all_results = _ping_results.get(target, [])
    rtts = [r["rtt_ms"] for r in all_results if r["rtt_ms"] is not None]
    timeouts = sum(1 for r in all_results if r.get("timeout", False))

    stats = {
        "total": len(all_results),
        "success": len(rtts),
        "timeouts": timeouts,
        "loss_pct": round(timeouts / len(all_results) * 100, 1) if all_results else 0,
        "min_ms": round(min(rtts), 2) if rtts else None,
        "max_ms": round(max(rtts), 2) if rtts else None,
        "avg_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
    }

    return {
        "target": target,
        "active": _active_pings.get(target, False),
        "results": results,
        "stats": stats,
    }


@router.get("/active")
async def list_active():
    """List all active ping targets."""
    return {
        "active": {t: v for t, v in _active_pings.items() if v},
        "targets": list(_ping_results.keys()),
    }
