"""Flag-gated read-only OPC UA "Sidecar" overlay asset, fed by a background poll.

OFF by default (``settings.opcua_enabled``). When enabled with a tag-map at
``settings.opcua_config_path``, a background task polls the configured OPC UA server
on its interval, normalizes the readings, and caches the latest ``VitalSign`` list in
memory. ``opcua_assets()`` surfaces that cache as a single Asset appended to /assets.

Safety contract (identical to reference_assets / process_assets):
* NEVER touches the SQLite registry / seed — the cache is purely in-memory
  (cf. incidents that broke the seed when assets were written).
* NEVER raises into the endpoint — any error degrades to ``[]``.
* Read-only — there is no OPC UA write path anywhere (IL-9000).
* Fully inert when ``opcua_enabled`` is False: the poller never starts and the
  overlay returns ``[]`` immediately, so /assets is byte-for-byte unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.config import settings
from src.models.asset import Asset

if TYPE_CHECKING:
    from src.models.telemetry import VitalSign

log = structlog.get_logger().bind(component="opcua_assets")

_HEALTH = {"bad": 35, "warn": 70, "good": 96, "unknown": None}

# In-memory latest snapshot — NEVER persisted.
_snap: dict = {
    "vitals": [],
    "asset_id": "",
    "name": "",
    "last_seen": None,
    "reachable": False,
}
_task: asyncio.Task | None = None


def _worst(vitals: list[VitalSign]) -> str:
    sv = {getattr(v, "status", "") for v in vitals}
    if "bad" in sv:
        return "bad"
    if "warn" in sv:
        return "warn"
    return "good" if vitals else "unknown"


def opcua_assets() -> list[Asset]:
    """Return the OPC UA overlay asset when enabled + populated; [] otherwise/on error."""
    if not settings.opcua_enabled:
        return []
    try:
        vitals = _snap["vitals"]
        if not vitals or _snap["last_seen"] is None:
            return []  # enabled, but no successful poll yet
        status = _worst(vitals) if _snap["reachable"] else "bad"
        return [
            Asset(
                id=_snap["asset_id"] or "OPCUA-01",
                type="sensor",
                status=status,
                name=_snap["name"] or _snap["asset_id"] or "OPC UA Source",
                location="OPC UA server (Sidecar — read-only)",
                health=_HEALTH.get(status),
                last_seen=_snap["last_seen"],
                vendor="(OPC UA)",
                model="OPC UA client (northbound)",
                protocol="opcua",
                vitals=list(vitals),
            )
        ]
    except Exception as e:  # noqa: BLE001 — must never break /assets
        log.warning("opcua_assets_failed", error=str(e))
        return []


async def _poll_loop() -> None:
    """Background loop: poll the OPC UA server, normalize, refresh the snapshot."""
    from src.collectors.opcua_client import load_opcua_config
    from src.engine.normalizer import normalize_batch

    try:
        cfg = load_opcua_config(settings.opcua_config_path)
    except Exception as e:  # noqa: BLE001 — bad/missing config: log and stop, never crash
        log.error("opcua_config_load_failed", path=settings.opcua_config_path, error=str(e))
        return

    _snap["asset_id"] = cfg.asset_id
    _snap["name"] = cfg.name
    collector = cfg.to_collector()
    interval = max(2, cfg.poll_interval)
    log.info("opcua_poll_loop_started", asset_id=cfg.asset_id, endpoint=cfg.endpoint, interval=interval)
    try:
        while True:
            readings = await collector.safe_poll()  # safe_poll never raises
            if readings:
                _snap["vitals"] = normalize_batch(readings)
                _snap["last_seen"] = datetime.now(UTC)
                _snap["reachable"] = True
            else:
                _snap["reachable"] = False
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise
    finally:
        with contextlib.suppress(Exception):  # teardown must never raise
            await collector.aclose()


async def start_opcua_poller() -> None:
    """Start the background poll loop IFF the flag is on and a config path is set.

    No-op when disabled (the common case), so calling this unconditionally at startup
    leaves a flag-off deployment completely unchanged.
    """
    global _task
    if not settings.opcua_enabled:
        return
    if not settings.opcua_config_path:
        log.warning("opcua_enabled_but_no_config_path")
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_poll_loop())


async def stop_opcua_poller() -> None:
    """Cancel the background poll loop if it is running."""
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _task
    _task = None
