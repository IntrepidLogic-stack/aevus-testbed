"""
Aevus — DNP3 Master Collector
IEEE 1815 (DNP3) protocol implementation for polling SCADA outstations.

DNP3 is the dominant protocol in oil & gas, water/wastewater, and electric
utility SCADA systems. This collector acts as a DNP3 Master, polling
outstations (field RTUs) for analog inputs, binary inputs, and counters.

Transport: DNP3 over TCP/IP (port 20000 by default).

Frame format (DNP3 Transport over TCP):
  [0x0564] Start bytes
  [length] Data length
  [ctrl]   Control byte
  [dst_lo] [dst_hi] Destination address (outstation)
  [src_lo] [src_hi] Source address (master)
  [crc_lo] [crc_hi] CRC-16
  [transport] Transport header
  [app_ctrl] Application control
  [func_code] Function code
  [object headers + data...]

Supported function codes:
  0x01 - READ (master requests data)
  0x81 - RESPONSE (outstation returns data)

Supported object groups:
  Group 30 - Analog Input (Var 1 = 32-bit with flag, Var 5 = float with flag)
  Group  1 - Binary Input (Var 2 = with flag)
  Group 20 - Counter (Var 1 = 32-bit with flag)
"""
from __future__ import annotations

import asyncio
import struct

import structlog

from src.collectors.base import BaseCollector
from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()

# DNP3 Constants
DNP3_START = 0x0564
DNP3_PORT = 20000
FUNC_READ = 0x01
FUNC_RESPONSE = 0x81
FUNC_DIRECT_OPERATE = 0x03

# Object groups
GROUP_BINARY_INPUT = 1
GROUP_COUNTER = 20
GROUP_ANALOG_INPUT = 30
GROUP_ANALOG_OUTPUT = 40
GROUP_CLASS_0 = 60  # Class 0 — static data (all points)

# Qualifiers
QUAL_ALL_POINTS = 0x06        # All points, no range
QUAL_RANGE_8BIT = 0x00        # Start-stop 8-bit index
QUAL_RANGE_16BIT = 0x01       # Start-stop 16-bit index

# CRC-16 lookup table for DNP3 (polynomial 0x3D65)
_CRC_TABLE = None


def _build_crc_table():
    global _CRC_TABLE
    _CRC_TABLE = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
        _CRC_TABLE.append(crc & 0xFFFF)


def _crc16(data: bytes) -> int:
    """Calculate DNP3 CRC-16."""
    if _CRC_TABLE is None:
        _build_crc_table()
    crc = 0x0000
    for b in data:
        crc = (_CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)) & 0xFFFF
    return crc ^ 0xFFFF


def _build_read_request(
    src_addr: int,
    dst_addr: int,
    group: int,
    variation: int,
    qualifier: int = QUAL_ALL_POINTS,
    start: int = 0,
    stop: int = 0,
    seq: int = 0,
) -> bytes:
    """Build a DNP3 READ request frame."""
    # Application layer
    app_ctrl = 0xC0 | (seq & 0x0F)  # FIR=1, FIN=1, SEQ
    app_data = bytes([app_ctrl, FUNC_READ])

    # Object header
    if qualifier == QUAL_ALL_POINTS:
        obj_header = struct.pack("BBB", group, variation, QUAL_ALL_POINTS)
    elif qualifier == QUAL_RANGE_8BIT:
        obj_header = struct.pack("BBBBB", group, variation, QUAL_RANGE_8BIT, start, stop)
    else:
        obj_header = struct.pack("<BBBHH", group, variation, QUAL_RANGE_16BIT, start, stop)

    app_data += obj_header

    # Transport header (FIR=1, FIN=1, SEQ=0)
    transport = bytes([0xC0])

    # Data link layer
    payload = transport + app_data
    length = len(payload) + 5  # 5 = ctrl + dst(2) + src(2)

    # Control byte: DIR=1 (master->outstation), PRM=1, FCV=0, FC=4 (unconfirmed user data)
    ctrl = 0xC4

    header = struct.pack("<HBBHH", DNP3_START, length, ctrl, dst_addr, src_addr)
    header_crc = struct.pack("<H", _crc16(header))

    # Build complete frame with CRC blocks (every 16 bytes of user data gets a CRC)
    frame = header + header_crc
    # Add data blocks with CRCs (16 bytes per block max)
    i = 0
    while i < len(payload):
        block = payload[i:i + 16]
        frame += block + struct.pack("<H", _crc16(block))
        i += 16

    return frame


def _parse_response(data: bytes, expected_src: int = 0) -> dict:
    """Parse a DNP3 response frame. Returns dict with parsed objects."""
    result = {"valid": False, "objects": [], "error": None}

    if len(data) < 10:
        result["error"] = "Frame too short"
        return result

    # Verify start bytes
    start = struct.unpack("<H", data[0:2])[0]
    if start != DNP3_START:
        result["error"] = f"Invalid start bytes: {start:#06x}"
        return result

    length = data[2]
    data[3]
    struct.unpack("<H", data[4:6])[0]
    struct.unpack("<H", data[6:8])[0]

    # Verify header CRC
    header_crc = struct.unpack("<H", data[8:10])[0]
    calc_crc = _crc16(data[0:8])
    if header_crc != calc_crc:
        result["error"] = f"Header CRC mismatch: {header_crc:#06x} != {calc_crc:#06x}"
        return result

    # Extract payload (strip CRCs from data blocks)
    payload = bytearray()
    pos = 10
    remaining = length - 5  # subtract ctrl + addresses
    while remaining > 0 and pos < len(data):
        block_size = min(16, remaining)
        if pos + block_size + 2 > len(data):
            break
        block = data[pos:pos + block_size]
        payload.extend(block)
        pos += block_size + 2  # skip CRC
        remaining -= block_size

    if len(payload) < 3:
        result["error"] = "Payload too short"
        return result

    # Transport header
    payload[0]

    # Application layer
    payload[1]
    func_code = payload[2]

    if func_code != FUNC_RESPONSE:
        result["error"] = f"Not a response: FC={func_code:#04x}"
        return result

    # Check IIN (Internal Indications) bytes
    if len(payload) < 5:
        result["error"] = "Missing IIN bytes"
        return result
    iin1 = payload[3]
    iin2 = payload[4]

    # Parse object headers starting at offset 5
    offset = 5
    while offset < len(payload):
        if offset + 3 > len(payload):
            break

        group = payload[offset]
        variation = payload[offset + 1]
        qualifier = payload[offset + 2]
        offset += 3

        if qualifier == QUAL_ALL_POINTS:
            # No range field — count determined by remaining data
            pass
        elif qualifier == QUAL_RANGE_8BIT:
            if offset + 2 > len(payload):
                break
            start_idx = payload[offset]
            stop_idx = payload[offset + 1]
            offset += 2
            stop_idx - start_idx + 1
        elif qualifier == QUAL_RANGE_16BIT:
            if offset + 4 > len(payload):
                break
            start_idx = struct.unpack("<H", payload[offset:offset + 2])[0]
            stop_idx = struct.unpack("<H", payload[offset + 2:offset + 4])[0]
            offset += 4
            stop_idx - start_idx + 1
        else:
            break

        # Parse objects based on group/variation
        if group == GROUP_ANALOG_INPUT:
            if variation == 5:  # Float with flag
                point_size = 5  # 1 flag + 4 float
                idx = start_idx if qualifier != QUAL_ALL_POINTS else 0
                while offset + point_size <= len(payload):
                    flag = payload[offset]
                    value = struct.unpack("<f", payload[offset + 1:offset + 5])[0]
                    result["objects"].append({
                        "group": group, "variation": variation,
                        "index": idx, "value": value,
                        "online": bool(flag & 0x01),
                        "type": "analog",
                    })
                    offset += point_size
                    idx += 1
                    if qualifier != QUAL_ALL_POINTS and idx > stop_idx:
                        break
            elif variation == 1:  # 32-bit integer with flag
                point_size = 5  # 1 flag + 4 int32
                idx = start_idx if qualifier != QUAL_ALL_POINTS else 0
                while offset + point_size <= len(payload):
                    flag = payload[offset]
                    value = struct.unpack("<i", payload[offset + 1:offset + 5])[0]
                    result["objects"].append({
                        "group": group, "variation": variation,
                        "index": idx, "value": float(value),
                        "online": bool(flag & 0x01),
                        "type": "analog",
                    })
                    offset += point_size
                    idx += 1
                    if qualifier != QUAL_ALL_POINTS and idx > stop_idx:
                        break

        elif group == GROUP_BINARY_INPUT:
            if variation == 2:  # With flag
                idx = start_idx if qualifier != QUAL_ALL_POINTS else 0
                while offset < len(payload):
                    flag = payload[offset]
                    value = 1.0 if (flag & 0x80) else 0.0
                    result["objects"].append({
                        "group": group, "variation": variation,
                        "index": idx, "value": value,
                        "online": bool(flag & 0x01),
                        "type": "binary",
                    })
                    offset += 1
                    idx += 1
                    if qualifier != QUAL_ALL_POINTS and idx > stop_idx:
                        break

        elif group == GROUP_COUNTER:
            if variation == 1:  # 32-bit with flag
                point_size = 5
                idx = start_idx if qualifier != QUAL_ALL_POINTS else 0
                while offset + point_size <= len(payload):
                    flag = payload[offset]
                    value = struct.unpack("<I", payload[offset + 1:offset + 5])[0]
                    result["objects"].append({
                        "group": group, "variation": variation,
                        "index": idx, "value": float(value),
                        "online": bool(flag & 0x01),
                        "type": "counter",
                    })
                    offset += point_size
                    idx += 1
                    if qualifier != QUAL_ALL_POINTS and idx > stop_idx:
                        break
        else:
            break

    result["valid"] = True
    result["iin"] = {"iin1": iin1, "iin2": iin2}
    return result


# ── DNP3 Point Map for Meter Station RTU ──────────────────────────
# Typical gas pipeline meter station / EFM point configuration
# Maps DNP3 analog input index → metric name, unit, group

DNP3_ANALOG_MAP = {
    # --- Flow Measurement (EFM) ---
    0:  {"metric": "differential_pressure", "unit": "inH2O", "group": "efm"},
    1:  {"metric": "static_pressure",       "unit": "PSIG",  "group": "efm"},
    2:  {"metric": "flow_temperature",      "unit": "°F",    "group": "efm"},
    3:  {"metric": "flow_rate",             "unit": "MCFD",  "group": "efm"},
    4:  {"metric": "accumulated_volume",    "unit": "MCF",   "group": "efm"},
    5:  {"metric": "energy_rate",           "unit": "MMBTU/D","group": "efm"},

    # --- Chromatograph / Gas Quality ---
    6:  {"metric": "btu_content",           "unit": "BTU/CF", "group": "gas_quality"},
    7:  {"metric": "specific_gravity",      "unit": "SG",     "group": "gas_quality"},
    8:  {"metric": "co2_content",           "unit": "%",      "group": "gas_quality"},
    9:  {"metric": "h2s_content",           "unit": "PPM",    "group": "gas_quality"},

    # --- Valve / Regulator ---
    10: {"metric": "upstream_pressure",     "unit": "PSIG",  "group": "regulation"},
    11: {"metric": "downstream_pressure",   "unit": "PSIG",  "group": "regulation"},
    12: {"metric": "valve_position",        "unit": "%",     "group": "regulation"},

    # --- Power / Environment ---
    13: {"metric": "battery_voltage",       "unit": "VDC",   "group": "power"},
    14: {"metric": "solar_voltage",         "unit": "VDC",   "group": "power"},
    15: {"metric": "charge_current",        "unit": "A",     "group": "power"},
    16: {"metric": "enclosure_temp",        "unit": "°F",    "group": "environment"},
    17: {"metric": "ambient_temp",          "unit": "°F",    "group": "environment"},

    # --- Pipeline ---
    18: {"metric": "line_pressure",         "unit": "PSIG",  "group": "pipeline"},
    19: {"metric": "line_temperature",      "unit": "°F",    "group": "pipeline"},
}

DNP3_BINARY_MAP = {
    0: {"metric": "valve_open",            "group": "regulation"},
    1: {"metric": "valve_closed",          "group": "regulation"},
    2: {"metric": "high_pressure_alarm",   "group": "safety"},
    3: {"metric": "low_pressure_alarm",    "group": "safety"},
    4: {"metric": "high_temp_alarm",       "group": "safety"},
    5: {"metric": "low_battery_alarm",     "group": "power"},
    6: {"metric": "communication_active",  "group": "system"},
    7: {"metric": "esd_activated",         "group": "safety"},
    8: {"metric": "h2s_alarm",             "group": "safety"},
    9: {"metric": "tamper_detect",         "group": "security"},
}

DNP3_COUNTER_MAP = {
    0: {"metric": "total_volume",          "unit": "MCF",   "group": "efm"},
    1: {"metric": "total_energy",          "unit": "MMBTU", "group": "efm"},
    2: {"metric": "comm_success_count",    "unit": "count", "group": "system"},
    3: {"metric": "comm_failure_count",    "unit": "count", "group": "system"},
}


class DNP3Collector(BaseCollector):
    """
    DNP3 Master collector for SCADA outstations.

    Polls a DNP3 outstation (field RTU) over TCP/IP for:
      - Analog Inputs (Group 30) — pressures, temps, flow, voltages
      - Binary Inputs (Group 1)  — valve status, alarms, ESD
      - Counters (Group 20)      — accumulated volumes, comm stats

    Designed for pipeline meter stations with EFM (Electronic Flow Measurement).
    """

    def __init__(
        self,
        asset_id: str,
        host: str,
        port: int = 20000,
        master_addr: int = 1,
        outstation_addr: int = 10,
        poll_interval: int = 10,
    ):
        super().__init__(asset_id, host, poll_interval)
        self.port = port
        self.master_addr = master_addr
        self.outstation_addr = outstation_addr
        self._seq = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    def _next_seq(self) -> int:
        """Increment and return the next sequence number (0-15)."""
        self._seq = (self._seq + 1) & 0x0F
        return self._seq

    async def _connect(self) -> None:
        """Establish TCP connection to the outstation."""
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=5.0,
        )
        self.log.info("dnp3_connected", host=self.host, port=self.port,
                      master=self.master_addr, outstation=self.outstation_addr)

    async def _disconnect(self) -> None:
        """Close the TCP connection."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _send_and_receive(self, frame: bytes, timeout: float = 5.0) -> bytes:
        """Send a DNP3 frame and wait for response."""
        await self._connect()
        self._writer.write(frame)
        await self._writer.drain()

        # Read response — DNP3 frames start with 0x0564
        response = await asyncio.wait_for(
            self._reader.read(4096),
            timeout=timeout,
        )
        return response

    async def is_reachable(self) -> bool:
        """Check if the outstation responds to a Class 0 read."""
        try:
            frame = _build_read_request(
                src_addr=self.master_addr,
                dst_addr=self.outstation_addr,
                group=GROUP_CLASS_0,
                variation=1,
                qualifier=QUAL_ALL_POINTS,
                seq=self._next_seq(),
            )
            response = await self._send_and_receive(frame, timeout=3.0)
            result = _parse_response(response)
            return result["valid"]
        except Exception:
            await self._disconnect()
            return False

    async def poll(self) -> list[RawTelemetry]:
        """Poll the outstation for all analog, binary, and counter data."""
        readings: list[RawTelemetry] = []

        try:
            # Read Analog Inputs (Group 30, Variation 5 = float with flag)
            frame = _build_read_request(
                src_addr=self.master_addr,
                dst_addr=self.outstation_addr,
                group=GROUP_ANALOG_INPUT,
                variation=5,
                qualifier=QUAL_RANGE_16BIT,
                start=0,
                stop=len(DNP3_ANALOG_MAP) - 1,
                seq=self._next_seq(),
            )
            response = await self._send_and_receive(frame)
            result = _parse_response(response)

            if result["valid"]:
                for obj in result["objects"]:
                    if obj["type"] == "analog" and obj["index"] in DNP3_ANALOG_MAP:
                        mapping = DNP3_ANALOG_MAP[obj["index"]]
                        readings.append(self._make_reading(
                            metric=mapping["metric"],
                            value=round(obj["value"], 3),
                            unit=mapping["unit"],
                            source="dnp3",
                            group=mapping["group"],
                        ))

            # Small delay between requests (outstation processing time)
            await asyncio.sleep(0.1)

            # Read Binary Inputs (Group 1, Variation 2 = with flag)
            frame = _build_read_request(
                src_addr=self.master_addr,
                dst_addr=self.outstation_addr,
                group=GROUP_BINARY_INPUT,
                variation=2,
                qualifier=QUAL_RANGE_8BIT,
                start=0,
                stop=len(DNP3_BINARY_MAP) - 1,
                seq=self._next_seq(),
            )
            response = await self._send_and_receive(frame)
            result = _parse_response(response)

            if result["valid"]:
                for obj in result["objects"]:
                    if obj["type"] == "binary" and obj["index"] in DNP3_BINARY_MAP:
                        mapping = DNP3_BINARY_MAP[obj["index"]]
                        readings.append(self._make_reading(
                            metric=mapping["metric"],
                            value=obj["value"],
                            unit="bool",
                            source="dnp3",
                            group=mapping["group"],
                        ))

            await asyncio.sleep(0.1)

            # Read Counters (Group 20, Variation 1 = 32-bit with flag)
            frame = _build_read_request(
                src_addr=self.master_addr,
                dst_addr=self.outstation_addr,
                group=GROUP_COUNTER,
                variation=1,
                qualifier=QUAL_RANGE_8BIT,
                start=0,
                stop=len(DNP3_COUNTER_MAP) - 1,
                seq=self._next_seq(),
            )
            response = await self._send_and_receive(frame)
            result = _parse_response(response)

            if result["valid"]:
                for obj in result["objects"]:
                    if obj["type"] == "counter" and obj["index"] in DNP3_COUNTER_MAP:
                        mapping = DNP3_COUNTER_MAP[obj["index"]]
                        readings.append(self._make_reading(
                            metric=mapping["metric"],
                            value=obj["value"],
                            unit=mapping["unit"],
                            source="dnp3",
                            group=mapping["group"],
                        ))

        except Exception as e:
            self.log.error("dnp3_poll_failed", error=str(e))
            await self._disconnect()
            raise

        return readings

    async def close(self) -> None:
        """Close the DNP3 TCP connection."""
        await self._disconnect()
