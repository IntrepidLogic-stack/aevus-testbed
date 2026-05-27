"""
Aevus Testbed — SNMP Trap Receiver (Phase 1 — Event-Driven Edge)

Listens on UDP 162 for SNMPv2c traps from lab devices (Trio JR900 radios,
MikroTik L009, Cisco Catalyst 2960, future field gear). Decodes incoming
PDUs, maps the source IP to an asset_id via the SQLite registry, and
publishes a structured TrapEvent onto an asyncio.Queue consumed by the
scheduler's trap-consumer loop.

Why this exists:
  Polling alone leaves a 5-30s blind window between scrapes. Cable
  unplug, cold start, and auth-failure events are surfaced by the device
  *immediately* via traps. A trap receiver closes the visibility gap to
  sub-second on every SNMP-managed device.

Privileges:
  Binding UDP 162 requires CAP_NET_BIND_SERVICE on Linux. The systemd
  unit shipped with this module grants that capability without running
  as root. See deploy/aevus-trap-receiver.service.

SNMP version:
  v2c only for now (matches lab gear configuration). v3 authPriv is the
  right answer for production / federal pursuits — layer in later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


# ──────────────────────────────────────────────────────────────────────────
# Standard SNMP trap OIDs (RFC 3418 / RFC 1215)
# ──────────────────────────────────────────────────────────────────────────
SNMP_TRAP_OIDS: dict[str, str] = {
    "1.3.6.1.6.3.1.1.5.1": "coldStart",
    "1.3.6.1.6.3.1.1.5.2": "warmStart",
    "1.3.6.1.6.3.1.1.5.3": "linkDown",
    "1.3.6.1.6.3.1.1.5.4": "linkUp",
    "1.3.6.1.6.3.1.1.5.5": "authenticationFailure",
    "1.3.6.1.6.3.1.1.5.6": "egpNeighborLoss",
}

# Trap-OID varbind (always present on SNMPv2 traps).
SNMP_TRAP_OID_BINDING = "1.3.6.1.6.3.1.1.4.1.0"
# sysUpTime varbind (always present on SNMPv2 traps).
SYS_UPTIME_BINDING = "1.3.6.1.2.1.1.3.0"
# Standard linkDown/linkUp interface index varbind.
IF_INDEX_BINDING = "1.3.6.1.2.1.2.2.1.1"


@dataclass
class TrapEvent:
    """A decoded SNMPv2c trap, ready for the alert engine.

    Attributes:
        event_type: Friendly name for the trap (e.g. "linkDown"). For
            vendor-specific OIDs that aren't in SNMP_TRAP_OIDS, this is
            the raw OID string.
        trap_oid: The raw snmpTrapOID value from the PDU.
        source_ip: IP address the trap came from (used for asset lookup).
        asset_id: Resolved asset ID, or None if no asset matches source_ip.
        community: SNMP community string the trap was sent with.
        varbinds: All varbinds from the PDU, keyed by OID string.
        received_at: When the trap was received by this process.
    """

    event_type: str
    trap_oid: str
    source_ip: str
    asset_id: str | None
    community: str
    varbinds: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Callback that resolves an IP to an asset_id. Injected at construction
# so the receiver doesn't depend directly on the DB layer (easier to
# test, easier to swap for an in-memory cache later).
AssetResolver = Callable[[str], str | None]


class SNMPTrapReceiver:
    """Async UDP 162 SNMPv2c trap listener.

    Decodes incoming traps and publishes TrapEvent objects onto
    self.events. Consumers (the scheduler) await events from the queue.

    The receiver runs as a background asyncio task started via start()
    and stopped via stop(). It is safe to call start() multiple times;
    the second call is a no-op.

    Implementation note: pysnmp's v6 asyncio API is used directly rather
    than the hlapi sugar, because we need access to the raw transport
    info (source IP) which the sugar layer hides.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 162,
        community: str = "aevus_trap",
        asset_resolver: AssetResolver | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.community = community
        self.asset_resolver: AssetResolver = asset_resolver or (lambda _ip: None)
        self.events: asyncio.Queue[TrapEvent] = asyncio.Queue()
        self.log = logger.bind(component="snmp_trap_receiver", port=port)

        self._engine: Any = None  # pysnmp SnmpEngine — lazy-imported in start()
        self._started: bool = False
        self._stopped: bool = False

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind UDP 162 and begin receiving traps."""
        if self._started:
            return
        self._started = True

        # Lazy import so the rest of the codebase isn't forced to import
        # pysnmp at module-load time (keeps unit tests light and lets
        # this module be imported on a dev machine without UDP 162 perms).
        from pysnmp.carrier.asyncio.dgram import udp
        from pysnmp.entity import config, engine
        from pysnmp.entity.rfc3413 import ntfrcv

        snmp_engine = engine.SnmpEngine()
        self._engine = snmp_engine

        # UDP transport on (host, port). Will raise PermissionError if the
        # process lacks CAP_NET_BIND_SERVICE on Linux.
        #
        # pysnmp 7.x note: the API was renamed from camelCase to
        # snake_case. We use the new names directly; aliases still
        # work but generate deprecation warnings on every call AND may
        # have subtle behavioral differences (observed: trap socket
        # appearing bound but not actually receiving). The new names
        # take the same arguments — see pysnmp.entity.config docs.
        try:
            config.add_transport(
                snmp_engine,
                udp.DOMAIN_NAME + (1,),
                udp.UdpTransport().open_server_mode((self.host, self.port)),
            )
        except Exception as e:
            self.log.error("trap_bind_failed", host=self.host, port=self.port, error=str(e))
            raise

        # SNMPv2c community config: accept traps from any source IP that
        # presents the configured community string. v3 authPriv comes
        # later — for now this is the lab posture.
        config.add_v1_system(snmp_engine, "aevus-trap-area", self.community)

        # Notification receiver wires the PDU-decode callback.
        ntfrcv.NotificationReceiver(snmp_engine, self._on_trap)
        snmp_engine.transport_dispatcher.job_started(1)

        self.log.info("trap_receiver_started", host=self.host, port=self.port)

    async def stop(self) -> None:
        """Stop receiving traps and close the UDP socket."""
        if self._stopped or not self._started:
            return
        self._stopped = True

        try:
            if self._engine is not None:
                self._engine.transport_dispatcher.close_dispatcher()
        except Exception as e:
            self.log.warning("trap_receiver_stop_error", error=str(e))
        self.log.info("trap_receiver_stopped")

    # ──────────────────────────────────────────────────────────────────
    # PDU decode callback
    # ──────────────────────────────────────────────────────────────────

    def _on_trap(
        self,
        snmp_engine: Any,
        state_reference: Any,
        context_engine_id: Any,
        context_name: Any,
        var_binds: Any,
        cb_ctx: Any,
    ) -> None:
        """pysnmp invokes this on every received trap PDU.

        Synchronous because pysnmp's notification API is sync, but we
        publish to an asyncio.Queue which is safe to put_nowait on from
        the event loop thread.
        """
        try:
            # pysnmp 7.x: snake_case API. msg_and_pdu_dsp.get_transport_info().
            # Falls back to the legacy name if running against pysnmp 6.x for
            # any reason — both attributes exist in 7.x but the camelCase
            # one emits a deprecation warning.
            dsp = getattr(snmp_engine, "msg_and_pdu_dsp", None) or getattr(
                snmp_engine, "msgAndPduDsp", None
            )
            if dsp is None:
                raise AttributeError("snmp_engine has no msg_and_pdu_dsp")
            get_info = getattr(dsp, "get_transport_info", None) or dsp.getTransportInfo
            transport_domain, transport_address = get_info(state_reference)
            source_ip = str(transport_address[0])
        except Exception as e:
            self.log.warning("trap_transport_info_failed", error=str(e))
            source_ip = "0.0.0.0"

        # Convert pysnmp varbinds into a plain dict {oid: value}. pysnmp's
        # values are pyasn1 types; pretty-print them to plain Python.
        decoded: dict[str, Any] = {}
        trap_oid: str | None = None
        for oid, value in var_binds:
            oid_str = str(oid)
            decoded[oid_str] = _pyasn1_to_python(value)
            if oid_str == SNMP_TRAP_OID_BINDING:
                trap_oid = str(value)

        if trap_oid is None:
            # SNMPv1 trap, or malformed PDU. Drop with a warning.
            self.log.warning("trap_missing_trap_oid", source_ip=source_ip, varbinds=list(decoded))
            return

        event_type = SNMP_TRAP_OIDS.get(trap_oid, trap_oid)
        asset_id = self.asset_resolver(source_ip)

        event = TrapEvent(
            event_type=event_type,
            trap_oid=trap_oid,
            source_ip=source_ip,
            asset_id=asset_id,
            community=self.community,
            varbinds=decoded,
        )

        self.log.info(
            "trap_received",
            event_type=event_type,
            source_ip=source_ip,
            asset_id=asset_id,
            varbind_count=len(decoded),
        )

        # put_nowait is safe from any thread when the queue is unbounded.
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            # Defensive — our queue is unbounded so this shouldn't happen.
            self.log.error("trap_queue_full", source_ip=source_ip)


def _pyasn1_to_python(value: Any) -> Any:
    """Best-effort conversion of pyasn1 types to plain Python.

    pysnmp returns pyasn1 wrappers (Integer, OctetString, ObjectIdentity,
    etc.) which don't JSON-serialize cleanly. Downstream code in the
    alert engine, DB layer, and WebSocket broadcaster all expect Python
    primitives.
    """
    try:
        # Most pyasn1 numeric types support prettyPrint / int conversion.
        if hasattr(value, "prettyPrint"):
            pretty = value.prettyPrint()
            # Numeric types — try int then float.
            try:
                return int(pretty)
            except (ValueError, TypeError):
                pass
            try:
                return float(pretty)
            except (ValueError, TypeError):
                pass
            return pretty
        return str(value)
    except Exception:
        return repr(value)


# ──────────────────────────────────────────────────────────────────────────
# Standalone smoke-test entry point
# ──────────────────────────────────────────────────────────────────────────
async def _smoke_main() -> None:
    """Run the trap receiver standalone for smoke testing on the Pi.

    Usage on the Pi:
        sudo setcap cap_net_bind_service=+ep $(readlink -f $(which python3))
        python3 -m src.collectors.snmp_trap_receiver

    Then from another host:
        snmptrap -v2c -c aevus_trap <pi-ip> '' 1.3.6.1.6.3.1.1.5.1

    Handles SIGTERM (sent by Greengrass / systemd) cleanly so the UDP
    socket is released on shutdown instead of leaking.
    """
    import signal

    receiver = SNMPTrapReceiver(community="aevus_trap")
    await receiver.start()
    print(f"Listening for SNMPv2c traps on UDP {receiver.port}, community={receiver.community}")
    print("Send a test trap to verify. Ctrl+C or SIGTERM to stop.")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows or restricted env; KeyboardInterrupt still works.
            pass

    consumer_task = asyncio.create_task(_print_loop(receiver))
    try:
        await stop.wait()
    finally:
        print("\nStopping...")
        consumer_task.cancel()
        await receiver.stop()


async def _print_loop(receiver: SNMPTrapReceiver) -> None:
    """Pretty-print events for the smoke-test path."""
    try:
        while True:
            event = await receiver.events.get()
            print(f"  → {event.event_type:20s} from {event.source_ip:15s} oid={event.trap_oid}")
            for oid, value in event.varbinds.items():
                print(f"       {oid} = {value!r}")
    except asyncio.CancelledError:
        return


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_smoke_main())
