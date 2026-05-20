"""
Aevus Testbed — ICMP Layer-3 Probe (Phase 2 — Event-Driven Edge)

Sub-second L3 reachability check for every registered asset. Runs
independently of any application-layer poll so we can distinguish:

  • Device dead          → ICMP down + SNMP/Modbus down
  • Agent dead           → ICMP up   + SNMP/Modbus down
  • Path broken          → ICMP down + SNMP/Modbus up    (rare)
  • ICMP blocked         → ICMP down + everything else up (firewall)

The probe maintains a rolling window of ping results per asset. State
transitions (up ↔ degraded ↔ down) emit a ReachabilityEvent onto a
queue consumed by the scheduler, which routes to AlertEngine.

Privileges:
  Linux exposes ICMP via either raw sockets (CAP_NET_RAW) or
  unprivileged DGRAM sockets when the user's GID is inside
  /proc/sys/net/ipv4/ping_group_range. The Pi install script grants
  CAP_NET_RAW on the venv python; the unprivileged path is also
  supported via the icmp_privileged=False config knob.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog

from src.config import settings

logger = structlog.get_logger()


ReachabilityState = Literal["up", "degraded", "down", "unknown"]


@dataclass
class ReachabilityEvent:
    """Emitted only on state transitions, never on every ping."""

    asset_id: str
    host: str
    state: ReachabilityState
    previous_state: ReachabilityState
    loss_pct: float
    avg_rtt_ms: Optional[float]
    consecutive_failures: int
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class _ProbeState:
    """Rolling per-asset state. Internal to ICMPProbe."""

    asset_id: str
    host: str
    window: deque[Optional[float]] = field(default_factory=lambda: deque(maxlen=10))
    consecutive_failures: int = 0
    state: ReachabilityState = "unknown"

    def record(self, rtt_ms: Optional[float], window_size: int) -> None:
        # Resize the window if config changed since startup.
        if self.window.maxlen != window_size:
            self.window = deque(self.window, maxlen=window_size)
        self.window.append(rtt_ms)
        if rtt_ms is None:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

    @property
    def loss_pct(self) -> float:
        if not self.window:
            return 0.0
        failures = sum(1 for r in self.window if r is None)
        return (failures / len(self.window)) * 100.0

    @property
    def avg_rtt_ms(self) -> Optional[float]:
        successes = [r for r in self.window if r is not None]
        if not successes:
            return None
        return sum(successes) / len(successes)


class ICMPProbe:
    """Async ICMP probe for one or more assets.

    Register hosts via add_target(); start() begins the probe loop;
    state-transition events show up on self.events.

    The probe uses a single asyncio task that iterates registered
    targets per cycle (rather than one task per target). This keeps
    resource usage flat as the fleet scales and avoids hammering
    asyncio with hundreds of short-lived tasks at field scale.
    """

    def __init__(
        self,
        interval: Optional[float] = None,
        timeout: Optional[float] = None,
        window_size: Optional[int] = None,
        loss_warn_pct: Optional[float] = None,
        consecutive_down: Optional[int] = None,
        privileged: Optional[bool] = None,
    ) -> None:
        self.interval = interval if interval is not None else settings.icmp_probe_interval
        self.timeout = timeout if timeout is not None else settings.icmp_timeout
        self.window_size = window_size if window_size is not None else settings.icmp_window_size
        self.loss_warn_pct = loss_warn_pct if loss_warn_pct is not None else settings.icmp_loss_warn_pct
        self.consecutive_down = consecutive_down if consecutive_down is not None else settings.icmp_consecutive_down
        self.privileged = privileged if privileged is not None else settings.icmp_privileged

        self._targets: dict[str, _ProbeState] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self.events: asyncio.Queue[ReachabilityEvent] = asyncio.Queue()
        self.log = logger.bind(component="icmp_probe")

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def add_target(self, asset_id: str, host: str) -> None:
        """Register an asset for probing. Idempotent."""
        if asset_id in self._targets:
            self._targets[asset_id].host = host  # allow host updates
            return
        self._targets[asset_id] = _ProbeState(
            asset_id=asset_id,
            host=host,
            window=deque(maxlen=self.window_size),
        )
        self.log.info("icmp_target_added", asset_id=asset_id, host=host)

    def remove_target(self, asset_id: str) -> None:
        self._targets.pop(asset_id, None)

    @property
    def targets(self) -> list[str]:
        return list(self._targets.keys())

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._probe_loop())
        self.log.info(
            "icmp_probe_started",
            interval=self.interval,
            timeout=self.timeout,
            window_size=self.window_size,
            target_count=len(self._targets),
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self.log.info("icmp_probe_stopped")

    # ──────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────

    async def _probe_loop(self) -> None:
        """Main loop — one sweep per interval."""
        while not self._stop_event.is_set():
            cycle_start = asyncio.get_event_loop().time()
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("icmp_sweep_error", error=str(e))

            # Sleep the remainder of the interval (drift correction).
            elapsed = asyncio.get_event_loop().time() - cycle_start
            sleep_for = max(0.0, self.interval - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)
                break  # stop_event was set
            except asyncio.TimeoutError:
                continue  # normal — go to next cycle

    async def _sweep_once(self) -> None:
        """Ping every target once, in parallel."""
        if not self._targets:
            return

        tasks = [
            asyncio.create_task(self._ping_one(state))
            for state in self._targets.values()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _ping_one(self, state: _ProbeState) -> None:
        """Send one ping and update state. Emit ReachabilityEvent on transition."""
        rtt_ms = await self._do_ping(state.host)
        state.record(rtt_ms, self.window_size)

        new_state = self._classify(state)
        if new_state != state.state:
            previous = state.state
            state.state = new_state
            event = ReachabilityEvent(
                asset_id=state.asset_id,
                host=state.host,
                state=new_state,
                previous_state=previous,
                loss_pct=state.loss_pct,
                avg_rtt_ms=state.avg_rtt_ms,
                consecutive_failures=state.consecutive_failures,
            )
            self.log.info(
                "reachability_changed",
                asset_id=state.asset_id,
                host=state.host,
                state=new_state,
                previous=previous,
                loss_pct=round(state.loss_pct, 1),
                consecutive_failures=state.consecutive_failures,
            )
            try:
                self.events.put_nowait(event)
            except asyncio.QueueFull:
                self.log.error("icmp_queue_full", asset_id=state.asset_id)

    def _classify(self, state: _ProbeState) -> ReachabilityState:
        """Map rolling window stats → reachability state."""
        if state.consecutive_failures >= self.consecutive_down:
            return "down"
        if state.loss_pct >= self.loss_warn_pct and len(state.window) >= 2:
            return "degraded"
        # We need at least one successful ping in the window before
        # calling the asset "up" — avoids declaring "up" on cold start
        # before the first probe response arrives.
        if any(r is not None for r in state.window):
            return "up"
        return state.state if state.state != "unknown" else "unknown"

    async def _do_ping(self, host: str) -> Optional[float]:
        """Issue one ICMP echo. Returns RTT in ms or None on timeout.

        Lazy-imports icmplib so the rest of the codebase doesn't need
        the library installed (unit tests in particular).
        """
        try:
            from icmplib import async_ping
        except ImportError:
            self.log.error("icmplib_not_installed")
            return None

        try:
            host_obj = await async_ping(
                host,
                count=1,
                interval=0.1,
                timeout=self.timeout,
                privileged=self.privileged,
            )
            if host_obj.is_alive and host_obj.avg_rtt > 0:
                return float(host_obj.avg_rtt)
            return None
        except Exception as e:
            # Treat any ping error as a missed ping. Common cases:
            # PermissionError (no cap), socket.gaierror (DNS fail).
            self.log.warning("icmp_ping_error", host=host, error=str(e))
            return None


# ──────────────────────────────────────────────────────────────────────────
# Standalone smoke-test entry point
# ──────────────────────────────────────────────────────────────────────────
async def _smoke_main() -> None:
    """Run the ICMP probe standalone for smoke testing on the Pi.

    Usage on the Pi:
        python3 -m src.collectors.icmp_probe 192.168.88.1 192.168.88.252

    Or with named targets:
        python3 -m src.collectors.icmp_probe RTR-01=192.168.88.1
    """
    import sys
    import logging

    logging.basicConfig(level=logging.INFO)

    probe = ICMPProbe()
    args = sys.argv[1:] or ["192.168.88.1"]
    for i, spec in enumerate(args):
        if "=" in spec:
            asset_id, host = spec.split("=", 1)
        else:
            asset_id, host = f"ASSET-{i:02d}", spec
        probe.add_target(asset_id, host)

    await probe.start()
    print(f"Probing {probe.targets} every {probe.interval}s. Ctrl+C or SIGTERM to stop.")

    import signal as _signal
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async def _print():
        try:
            while True:
                event = await probe.events.get()
                print(
                    f"  → {event.asset_id:10s} {event.host:18s} "
                    f"{event.previous_state:9s} → {event.state:9s} "
                    f"loss={event.loss_pct:5.1f}%  rtt={event.avg_rtt_ms or 0.0:6.2f}ms"
                )
        except asyncio.CancelledError:
            return

    consumer = asyncio.create_task(_print())
    try:
        await stop.wait()
    finally:
        print("\nStopping...")
        consumer.cancel()
        await probe.stop()


if __name__ == "__main__":
    asyncio.run(_smoke_main())
