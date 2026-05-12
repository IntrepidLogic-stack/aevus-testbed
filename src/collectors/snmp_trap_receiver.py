"""
Aevus Testbed --- SNMP Trap Receiver
Async UDP listener for SNMPv2c traps on port 1162.
Converts traps to Alert objects, persists, and broadcasts via WebSocket.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.models.alert import Alert

if TYPE_CHECKING:
    from src.api.ws import ConnectionManager
    from src.storage.sqlite_db import SQLiteDB

logger = structlog.get_logger()

# ── IP -> (asset_id, asset_name) mapping ──
TRAP_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "192.168.88.1": ("RTR-01", "MikroTik L009"),
    "192.168.88.2": ("SW-01", "Catalyst 2960"),
    "192.168.88.11": ("RAD-01", "Trio JR900 #1"),
    "192.168.88.12": ("RAD-02", "Trio JR900 #2"),
    "192.168.88.21": ("RTU-01", "SCADAPack 470"),
    "192.168.88.254": ("EDGE-01", "Raspberry Pi"),
    # WireGuard tunnel peer
    "10.99.0.2": ("RTR-01", "MikroTik L009"),
}

# Standard SNMP trap OIDs
OID_COLD_START = "1.3.6.1.6.3.1.1.5.1"
OID_WARM_START = "1.3.6.1.6.3.1.1.5.2"
OID_LINK_DOWN = "1.3.6.1.6.3.1.1.5.3"
OID_LINK_UP = "1.3.6.1.6.3.1.1.5.4"
OID_AUTH_FAILURE = "1.3.6.1.6.3.1.1.5.5"

# Enterprise OID prefixes
OID_TRIO = "1.3.6.1.4.1.33302"
OID_CISCO = "1.3.6.1.4.1.9"

# sysUpTime.0 and snmpTrapOID.0
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SNMP_TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
# ifIndex / ifDescr
OID_IF_INDEX = "1.3.6.1.2.1.2.2.1.1"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"


# ── Minimal BER/ASN.1 decoder for SNMPv2c traps ──

def _decode_length(data: bytes, offset: int) -> tuple[int, int]:
    """Decode BER length. Returns (length, new_offset)."""
    b = data[offset]
    if b < 0x80:
        return b, offset + 1
    num_bytes = b & 0x7F
    length = int.from_bytes(data[offset + 1 : offset + 1 + num_bytes], "big")
    return length, offset + 1 + num_bytes


def _decode_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    """Decode one TLV. Returns (tag, value_bytes, new_offset)."""
    tag = data[offset]
    length, off = _decode_length(data, offset + 1)
    value = data[off : off + length]
    return tag, value, off + length


def _decode_oid(data: bytes) -> str:
    """Decode an ASN.1 OID value to dotted string."""
    if not data:
        return ""
    components = [str(data[0] // 40), str(data[0] % 40)]
    val = 0
    for b in data[1:]:
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            components.append(str(val))
            val = 0
    return ".".join(components)


def _decode_integer(data: bytes) -> int:
    return int.from_bytes(data, "big", signed=True)


def _decode_string(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.hex()


def _decode_value(tag: int, value: bytes) -> Any:
    """Decode an ASN.1 value based on tag."""
    if tag == 0x02:  # INTEGER
        return _decode_integer(value)
    if tag == 0x04:  # OCTET STRING
        return _decode_string(value)
    if tag == 0x06:  # OID
        return _decode_oid(value)
    if tag == 0x40:  # IpAddress
        return ".".join(str(b) for b in value)
    if tag == 0x41:  # Counter32
        return int.from_bytes(value, "big")
    if tag == 0x42:  # Gauge32
        return int.from_bytes(value, "big")
    if tag == 0x43:  # TimeTicks
        return int.from_bytes(value, "big")
    if tag == 0x46:  # Counter64
        return int.from_bytes(value, "big")
    if tag == 0x05:  # NULL
        return None
    return value.hex()


def _parse_varbinds(data: bytes, offset: int, end: int) -> list[tuple[str, Any]]:
    """Parse a SEQUENCE OF varbind pairs."""
    varbinds = []
    while offset < end:
        # Each varbind is a SEQUENCE of (OID, value)
        tag, seq_val, offset = _decode_tlv(data, offset)
        if tag != 0x30:
            continue
        inner_off = 0
        # OID
        oid_tag, oid_val, inner_off = _decode_tlv(seq_val, inner_off)
        oid_str = _decode_oid(oid_val) if oid_tag == 0x06 else str(oid_val)
        # Value
        val_tag, val_bytes, inner_off = _decode_tlv(seq_val, inner_off)
        val = _decode_value(val_tag, val_bytes)
        varbinds.append((oid_str, val))
    return varbinds


def parse_snmpv2c_trap(data: bytes) -> dict | None:
    """
    Parse a raw SNMPv2c trap PDU.
    Returns dict with 'community', 'trap_oid', 'varbinds' or None on failure.
    """
    try:
        off = 0
        # Outer SEQUENCE
        tag, outer_val, _ = _decode_tlv(data, off)
        if tag != 0x30:
            return None
        off = 0
        buf = outer_val

        # Version (INTEGER, should be 1 for v2c)
        tag, ver_val, off = _decode_tlv(buf, off)
        version = _decode_integer(ver_val)
        if version != 1:  # 0=v1, 1=v2c
            logger.warning("snmp_trap_unsupported_version", version=version)
            return None

        # Community string
        tag, comm_val, off = _decode_tlv(buf, off)
        community = _decode_string(comm_val)

        # PDU — tag 0xA7 for SNMPv2-Trap-PDU
        pdu_tag, pdu_val, off = _decode_tlv(buf, off)
        if pdu_tag != 0xA7:
            logger.warning("snmp_trap_wrong_pdu_type", pdu_tag=hex(pdu_tag))
            return None

        # Inside PDU: request-id, error-status, error-index, varbind-list
        poff = 0
        # request-id
        _, _, poff = _decode_tlv(pdu_val, poff)
        # error-status
        _, _, poff = _decode_tlv(pdu_val, poff)
        # error-index
        _, _, poff = _decode_tlv(pdu_val, poff)
        # varbind list (SEQUENCE OF)
        vb_tag, vb_val, poff = _decode_tlv(pdu_val, poff)
        if vb_tag != 0x30:
            return None

        varbinds = _parse_varbinds(vb_val, 0, len(vb_val))

        # Extract trap OID from varbinds (second varbind is snmpTrapOID.0)
        trap_oid = ""
        for oid, val in varbinds:
            if oid == OID_SNMP_TRAP_OID:
                trap_oid = val if isinstance(val, str) else str(val)
                break

        return {
            "community": community,
            "trap_oid": trap_oid,
            "varbinds": varbinds,
        }
    except Exception as e:
        logger.error("snmp_trap_parse_error", error=str(e))
        return None


# ── Trap handler logic ──

def _extract_if_info(varbinds: list[tuple[str, Any]]) -> tuple[int | None, str]:
    """Extract ifIndex and ifDescr from varbinds."""
    if_index = None
    if_descr = "unknown"
    for oid, val in varbinds:
        if oid.startswith(OID_IF_INDEX):
            if_index = val if isinstance(val, int) else None
        elif oid.startswith(OID_IF_DESCR):
            if_descr = str(val)
    return if_index, if_descr


def _make_alert(
    severity: str,
    asset_id: str,
    asset_name: str,
    message: str,
    risk_score: int | None = None,
) -> Alert:
    return Alert(
        id=f"ALT-{uuid.uuid4().hex[:8].upper()}",
        severity=severity,
        asset_id=asset_id,
        asset_name=asset_name,
        message=message,
        risk_score=risk_score,
        detected_at=datetime.now(UTC),
        status="open",
    )


class SNMPTrapReceiver:
    """Async SNMP trap listener using raw UDP sockets."""

    def __init__(
        self,
        db: SQLiteDB,
        ws_manager: ConnectionManager,
        port: int = 1162,
    ) -> None:
        self.db = db
        self.ws_manager = ws_manager
        self.port = port
        self.log = logger.bind(component="snmp_trap_receiver")
        self._transport: asyncio.DatagramTransport | None = None
        self._running = False
        # Track open linkDown alerts for auto-resolve: (asset_id, ifDescr) -> alert_id
        self._open_link_alerts: dict[tuple[str, str], str] = {}

    async def start(self) -> None:
        """Start listening for SNMP traps."""
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _TrapProtocol(self),
            local_addr=("0.0.0.0", self.port),
        )
        self._running = True
        self.log.info("snmp_trap_receiver_started", port=self.port)

    async def stop(self) -> None:
        """Stop the trap receiver."""
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None
        self.log.info("snmp_trap_receiver_stopped")

    async def handle_trap(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process a received SNMP trap."""
        source_ip = addr[0]
        self.log.info("snmp_trap_received", source=source_ip, bytes=len(data))

        parsed = parse_snmpv2c_trap(data)
        if not parsed:
            self.log.warning("snmp_trap_unparseable", source=source_ip)
            return

        trap_oid = parsed["trap_oid"]
        varbinds = parsed["varbinds"]

        # Resolve asset
        asset_id, asset_name = TRAP_SOURCE_MAP.get(
            source_ip, ("UNKNOWN", f"Unknown ({source_ip})")
        )

        self.log.info(
            "snmp_trap_parsed",
            source=source_ip,
            trap_oid=trap_oid,
            asset_id=asset_id,
            community=parsed["community"],
            varbind_count=len(varbinds),
        )

        alert = await self._classify_trap(trap_oid, varbinds, asset_id, asset_name)
        if alert:
            self.db.save_alert(alert)
            await self.ws_manager.broadcast(
                "alert_update", {"alerts": [alert.model_dump()]}
            )
            self.log.info(
                "snmp_trap_alert_created",
                alert_id=alert.id,
                severity=alert.severity,
                message=alert.message,
            )

    async def _classify_trap(
        self,
        trap_oid: str,
        varbinds: list[tuple[str, Any]],
        asset_id: str,
        asset_name: str,
    ) -> Alert | None:
        """Classify trap OID and create appropriate Alert."""

        # ── linkDown ──
        if trap_oid == OID_LINK_DOWN:
            if_index, if_descr = _extract_if_info(varbinds)
            # Uplink/trunk ports are critical; access ports are warning
            is_uplink = any(
                kw in if_descr.lower()
                for kw in ("trunk", "uplink", "sfp", "combo", "gigabit")
            )
            severity = "critical" if is_uplink else "warning"
            alert = _make_alert(
                severity=severity,
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"Port {if_descr} link down on {asset_name}",
                risk_score=90 if severity == "critical" else 60,
            )
            self._open_link_alerts[(asset_id, if_descr)] = alert.id
            return alert

        # ── linkUp ──
        if trap_oid == OID_LINK_UP:
            if_index, if_descr = _extract_if_info(varbinds)
            # Auto-resolve matching linkDown alert
            key = (asset_id, if_descr)
            if key in self._open_link_alerts:
                old_id = self._open_link_alerts.pop(key)
                try:
                    existing = self.db.get_alert(old_id)
                    if existing and existing.status == "open":
                        existing.status = "resolved"
                        existing.resolved_at = datetime.now(UTC)
                        self.db.save_alert(existing)
                        self.log.info("snmp_trap_auto_resolved", alert_id=old_id)
                except Exception:
                    pass
            return _make_alert(
                severity="info",
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"Port {if_descr} link restored on {asset_name}",
                risk_score=0,
            )

        # ── coldStart ──
        if trap_oid == OID_COLD_START:
            return _make_alert(
                severity="critical",
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"Cold start detected on {asset_name} — device was power cycled",
                risk_score=95,
            )

        # ── warmStart ──
        if trap_oid == OID_WARM_START:
            return _make_alert(
                severity="warning",
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"Warm start on {asset_name} — software restarted",
                risk_score=50,
            )

        # ── authenticationFailure ──
        if trap_oid == OID_AUTH_FAILURE:
            return _make_alert(
                severity="warning",
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"SNMP authentication failure on {asset_name} — unauthorized access attempt",
                risk_score=70,
            )

        # ── Trio JR900 enterprise traps ──
        if trap_oid.startswith(OID_TRIO):
            return _make_alert(
                severity="critical",
                asset_id=asset_id,
                asset_name=asset_name,
                message=f"Trio radio trap on {asset_name} — RF link event (OID: {trap_oid})",
                risk_score=85,
            )

        # ── Cisco enterprise traps ──
        if trap_oid.startswith(OID_CISCO):
            # Check for temperature-related traps
            is_temp = "envMon" in trap_oid or ".3.6.1.4.1.9.9.13" in trap_oid
            severity = "warning" if is_temp else "info"
            msg = (
                f"Cisco environment temperature alert on {asset_name}"
                if is_temp
                else f"Cisco enterprise trap on {asset_name} (OID: {trap_oid})"
            )
            return _make_alert(
                severity=severity,
                asset_id=asset_id,
                asset_name=asset_name,
                message=msg,
                risk_score=65 if is_temp else 30,
            )

        # ── Generic / unknown trap ──
        varbind_summary = "; ".join(f"{o}={v}" for o, v in varbinds[:5])
        self.log.info(
            "snmp_trap_unknown",
            trap_oid=trap_oid,
            varbinds=varbind_summary,
        )
        return _make_alert(
            severity="info",
            asset_id=asset_id,
            asset_name=asset_name,
            message=f"SNMP trap received on {asset_name} (OID: {trap_oid})",
            risk_score=10,
        )


class _TrapProtocol(asyncio.DatagramProtocol):
    """asyncio protocol adapter for UDP trap packets."""

    def __init__(self, receiver: SNMPTrapReceiver) -> None:
        self.receiver = receiver

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        asyncio.ensure_future(self.receiver.handle_trap(data, addr))

    def error_received(self, exc: Exception) -> None:
        logger.error("snmp_trap_udp_error", error=str(exc))
