"""
Bedrock RCA prompt assembly.

Kept separate from handler.py so we can unit-test prompt rendering
without standing up the full Lambda harness, and so prompt evolution
is reviewable in PRs (Bedrock output quality is highly sensitive to
prompt structure — every change should be diff-able).

Output contract (Claude-rendered JSON, parsed by handler.py):

    {
      "probable_cause":   "<one-sentence hypothesis>",
      "evidence":         ["...", "...", "..."],
      "severity":         "critical" | "warning" | "info",
      "recommended_action": "<concrete next step for the operator>",
      "confidence":        0.0 - 1.0,
      "supporting_assets": ["RTU-01", "RAD-01"]   // optional cross-asset hints
    }

Claude is instructed to return *only* this JSON, no preamble. The
handler validates against this schema and writes the validated
narrative to MQTT + S3 audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SYSTEM_PROMPT = """You are the Aevus SCADA Root-Cause Analyst — an AI \
expert in industrial control systems, SCADA telemetry, and incident \
investigation. You analyze alarms from midstream oil & gas \
infrastructure (compressor stations, pumping stations, gas \
processing) and produce concise, evidence-grounded root-cause \
narratives for control-room operators.

Your conduct is governed by ISA-101 (HMI design), IEC 62443 (industrial \
cybersecurity), and NIST 800-82 (ICS security). You treat every alarm \
as potentially safety-significant until evidence proves otherwise.

═══════════════════════════════════════════════════════════════════
EQUIPMENT REFERENCE — use these specs when reasoning about evidence
═══════════════════════════════════════════════════════════════════

SCADAPack 470 RTU (Schneider Electric)
  Protocols: Modbus TCP :502, DNP3 :20000 (outstation addr 10), unsolicited responses enabled
  Modbus holding-register map (Float32 pairs unless noted):
    40001 suction_pressure          PSI    | warn>800     critical>900
    40003 discharge_pressure        PSI    | warn>1200    critical>1400
    40005 flow_rate                 MCFD   |
    40007 gas_temperature           °F     |
    40009 ambient_temperature       °F     |
    40011 battery_voltage           VDC    | warn<12.0    critical<11.5
    40013 solar_voltage             VDC    |
    40015 tank_level                inches |
    40017 vibration                 mm/s   | warn>4.5     critical>7.1
    40019 run_hours                 hours (UInt32)
  Modbus discrete inputs:
    10001 compressor_running   10002 high_pressure_alarm
    10003 low_battery_alarm    10004 communication_fault

Trio JR900 radio (SNMPv2c, enterprise OID 1.3.6.1.4.1.5727)
  Key metrics (per asset, polled every 30s):
    rssi               dBm    | warn<-80     critical<-90
    snr                dB     | warn<15      critical<10
    tx_power           dBm
    temperature        °C     | warn>60      critical>75
    voltage            VDC
    error_packets      count  | rate warn>1% critical>5% of rx_packets
  Failure modes ordered by frequency: antenna degradation,
  RF interference, power supply, then radio firmware.

MikroTik L009UiGS-2HaxD router (SNMPv2c + traps to UDP 162)
  Standard MIB-II ifTable + system OIDs.
  Sends linkDown/linkUp traps. coldStart on boot/power-loss.

Cisco Catalyst 2960 (SNMPv2c)
  Standard ifTable + Cisco process/memory OIDs.

Network thresholds (any device class):
  cpu_load           warn>70%   critical>90%
  interface_errors   warn>100/min   critical>1000/min
  link_status        critical when down

═══════════════════════════════════════════════════════════════════
SITE CONTEXT
═══════════════════════════════════════════════════════════════════
Site: Needville lab cabinet (Texas, US Central time)
Edge collector: Raspberry Pi 4 (`aevus-edge-needville`), 192.168.88.254,
  running aevus.service (FastAPI + async collectors + alert engine).
Operations posture: pre-revenue test bed; alarms route to Woody Spencer
  (woody@intrepidlogic.io) and Lynn Spencer (chiefegr@intrepidlogic.io)
  via SNS email. No 24/7 NOC. Operator response time may exceed 30 min
  outside business hours.

═══════════════════════════════════════════════════════════════════
IL-9000 SAFETY INTERLOCK — PATENT P-008 (do not violate)
═══════════════════════════════════════════════════════════════════
IL-9000 is a hard-coded interlock in the Aevus platform that forbids
any automated write to PLC/RTU firmware or control registers. The
platform is read-only by design. The interlock is enforced in code via
a `IL_009_ENFORCED = True` constant referenced by every firmware-touching
function. Recommending a remote write is not just wrong — it is
impossible. Every corrective action that requires a write to a control
system MUST end in a credentialed-technician dispatch instruction.

═══════════════════════════════════════════════════════════════════
OUTPUT RULES — non-negotiable
═══════════════════════════════════════════════════════════════════
1. Respond with ONLY valid JSON matching the schema in the user \
prompt. No preamble. No markdown fences. No trailing text.
2. Never invent telemetry values or events not present in the \
context block. If evidence is thin, lower the confidence score and \
say so in the recommended_action.
3. Never recommend writes to PLC/RTU firmware or controls. Per the \
IL-9000 interlock above, the platform is read-only by design. If a \
corrective action requires a write, recommend dispatching a \
credentialed field technician.
4. Cite specific evidence in the `evidence` array — by event \
timestamp, metric name, or asset_id. Generic statements ("battery is \
low") are not evidence; "battery_voltage=11.2 VDC at 14:32:05Z, below \
critical threshold 11.5 VDC" is evidence.
5. confidence < 0.6 means an operator should investigate before \
acting. confidence ≥ 0.8 means the evidence is strong and the \
recommended_action is actionable. Calibrate against the equipment \
reference above: if a reading exceeds a documented critical threshold \
and recent telemetry corroborates it, your confidence should be high.
6. When the alarm is on a SCADAPack 470 process value (suction, \
discharge, vibration, etc.), always include the relevant adjacent \
process readings in your evidence (e.g., if discharge_pressure is \
high, mention what suction_pressure is doing). Cross-correlation \
across process points is how operators reason about root cause.
7. For radio alarms (Trio JR900), check the recent telemetry block \
for trends in RSSI/SNR/temperature/error_packets — a slow degradation \
points to antenna or hardware; a sudden change points to interference \
or power loss.
8. The CHATTERING SIGNALS block lists any metrics that fired the threshold \
N times in a short window (ISA-18.2 §7.5 "chattering"). A chattering metric \
is a quality-of-signal indicator — the reading is oscillating around the \
threshold rather than sustained-bad. Use chattering context this way: \
(a) if the TRIGGERING ALARM's metric is chattering, lower the confidence \
and recommend investigating sensor/threshold/deadband tuning before \
dispatching a technician (ISA-18.2 §7.5 calls chattering a deadband \
issue that should not auto-escalate); \
(b) if a DIFFERENT metric on the same asset is chattering, mention it in \
evidence as a co-symptom — chattering on temperature alongside a \
low_battery critical often shares a power-supply root cause; \
(c) NEVER treat a chattering meta-alarm as the primary cause. The \
meta-alarm is observability, not failure.
"""


USER_PROMPT_TEMPLATE = """An alarm has been generated by the Aevus \
platform. Analyze the context below and produce a root-cause narrative.

═══════════════ TRIGGERING ALARM ═══════════════
{alert_block}

═══════════════ ASSET ═══════════════
{asset_block}

═══════════════ RECENT EVENTS (last {event_window_minutes} min) ═══════════════
{events_block}

═══════════════ RECENT TELEMETRY (last {telemetry_window_minutes} min) ═══════════════
{telemetry_block}

═══════════════ RELATED ASSETS (same site) ═══════════════
{related_block}

═══════════════ CHATTERING SIGNALS (ISA-18.2 §7.5) ═══════════════
{chattering_block}

═══════════════ INSTRUCTIONS ═══════════════
Return a single JSON object with EXACTLY these keys and no others:

{{
  "probable_cause":     "<one-sentence hypothesis>",
  "evidence":           ["<cited fact 1>", "<cited fact 2>", "<cited fact 3>"],
  "severity":           "critical" | "warning" | "info",
  "recommended_action": "<concrete next step for the operator>",
  "confidence":         <float between 0.0 and 1.0>,
  "supporting_assets":  ["<asset_id>", ...]
}}

Respond with ONLY the JSON object. No other text.
"""


# Schema we validate Claude's response against. Strict — extra keys
# are dropped, missing keys → validation error → handler retries or
# falls back to a deterministic message.
RESPONSE_SCHEMA_KEYS = {
    "probable_cause",
    "evidence",
    "severity",
    "recommended_action",
    "confidence",
    "supporting_assets",
}

VALID_SEVERITIES = {"critical", "warning", "info"}


@dataclass
class PromptContext:
    """Everything the prompt needs. Built by context.py, consumed here.

    Keeping it as a single dataclass means prompt evolution doesn't
    cascade through call sites — add a field here, render it below.
    """

    alert: dict[str, Any]
    asset: dict[str, Any]
    recent_events: list[dict[str, Any]]
    recent_telemetry: list[dict[str, Any]]
    related_assets: list[dict[str, Any]]
    # Task #128: chattering meta-alarms from the same window. Empty list
    # is the common case — most alarms are not on a chattering metric.
    chattering_signals: list[dict[str, Any]] = field(default_factory=list)
    event_window_minutes: int = 15
    telemetry_window_minutes: int = 30


def render(context: PromptContext) -> tuple[str, str]:
    """Render (system, user) prompts.

    Returns a tuple matching Claude's anthropic_version messages API:
        system: str
        user:   str (single user turn, no multi-turn history)
    """
    user = USER_PROMPT_TEMPLATE.format(
        alert_block=_render_alert(context.alert),
        asset_block=_render_asset(context.asset),
        events_block=_render_events(context.recent_events),
        telemetry_block=_render_telemetry(context.recent_telemetry),
        related_block=_render_related(context.related_assets),
        chattering_block=_render_chattering(context.chattering_signals),
        event_window_minutes=context.event_window_minutes,
        telemetry_window_minutes=context.telemetry_window_minutes,
    )
    return SYSTEM_PROMPT, user


# ──────────────────────────────────────────────────────────────────────────
# Block renderers — each handles its own "no data" case
# ──────────────────────────────────────────────────────────────────────────
def _render_alert(alert: dict[str, Any]) -> str:
    if not alert:
        return "(no alert payload)"
    return (
        f"  id:        {alert.get('id', '?')}\n"
        f"  severity:  {alert.get('severity', '?')}\n"
        f"  asset_id:  {alert.get('asset_id', '?')}\n"
        f"  message:   {alert.get('message', '?')}\n"
        f"  detected:  {alert.get('detected_at', '?')}\n"
        f"  status:    {alert.get('status', '?')}"
    )


def _render_asset(asset: dict[str, Any]) -> str:
    if not asset:
        return "(asset metadata unavailable)"
    return (
        f"  id:        {asset.get('id', '?')}\n"
        f"  name:      {asset.get('name', '?')}\n"
        f"  type:      {asset.get('type', '?')}\n"
        f"  vendor:    {asset.get('vendor', '?')}\n"
        f"  model:     {asset.get('model', '?')}\n"
        f"  firmware:  {asset.get('firmware', 'unknown')}\n"
        f"  location:  {asset.get('location', '?')}\n"
        f"  ip:        {asset.get('ip_address', '?')}\n"
        f"  current_health: {asset.get('health', '?')} / 100\n"
        f"  current_status: {asset.get('status', '?')}\n"
        f"  last_seen: {asset.get('last_seen', '?')}"
    )


def _render_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "(no events in window)"
    lines = []
    for e in events[-50:]:  # cap to most recent 50 to bound token usage
        ts = e.get("ts") or e.get("received_at") or "?"
        etype = e.get("type") or e.get("event_class") or e.get("event_type") or "event"
        source = e.get("source", "?")
        payload = e.get("payload", e)
        # Compact one-liner per event.
        summary = _summarize_event(payload)
        lines.append(f"  [{ts}] {etype:14s} src={source:8s} {summary}")
    return "\n".join(lines)


def _render_telemetry(readings: list[dict[str, Any]]) -> str:
    if not readings:
        return "(no telemetry in window)"
    # Group by metric, render min/max/last so the model has shape
    # without 1000 individual data points.
    by_metric: dict[str, list[float]] = {}
    last_ts: dict[str, str] = {}
    units: dict[str, str] = {}
    for r in readings:
        m = r.get("metric", "?")
        v = r.get("value")
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        by_metric.setdefault(m, []).append(v)
        last_ts[m] = r.get("ts", last_ts.get(m, "?"))
        units[m] = r.get("unit", units.get(m, ""))

    if not by_metric:
        return "(no numeric telemetry)"

    lines = []
    for m in sorted(by_metric.keys()):
        values = by_metric[m]
        lines.append(
            f"  {m:24s} count={len(values):3d}  "
            f"min={min(values):>9.2f}  max={max(values):>9.2f}  "
            f"last={values[-1]:>9.2f} {units[m]}  "
            f"last_ts={last_ts[m]}"
        )
    return "\n".join(lines)


def _render_related(related: list[dict[str, Any]]) -> str:
    if not related:
        return "(no related assets to consider)"
    lines = []
    for a in related[:10]:  # cap context bloat
        lines.append(
            f"  {a.get('id', '?'):10s} {a.get('name', '?'):22s} "
            f"type={a.get('type', '?'):8s} status={a.get('status', '?'):8s} "
            f"health={a.get('health', '?')}"
        )
    return "\n".join(lines)


def _render_chattering(chattering: list[dict[str, Any]]) -> str:
    """Render chattering meta-alarms detected in the recent event window.

    Tells the LLM which metrics on this asset are oscillating around their
    threshold (per ISA-18.2 §7.5). The system prompt's Rule #8 explains how
    to use this — quality-of-signal indicator, not a primary cause.
    """
    if not chattering:
        return "(no chattering metrics — every threshold alarm in the window has been sustained, not oscillating)"
    lines = []
    for c in chattering[:8]:  # cap so a noisy site can't blow the prompt budget
        ts = c.get("detected_at") or "?"
        metric = c.get("metric") or "unknown"
        asset_id = c.get("asset_id") or "?"
        msg = (c.get("message") or "").strip()
        # Keep one line per chattering metric. Full message included so the
        # LLM sees the fire-count + window for context calibration.
        lines.append(f"  [{ts}] asset={asset_id} metric={metric}  — {msg}")
    if len(chattering) > 8:
        lines.append(f"  ... and {len(chattering) - 8} more (truncated)")
    return "\n".join(lines)


def _summarize_event(payload: dict[str, Any]) -> str:
    """One-line event summary tailored to common event payload shapes."""
    if not isinstance(payload, dict):
        return str(payload)[:120]
    # DNP3 / partial-telemetry: metric=value pairs
    if "metric" in payload and "value" in payload:
        lat = payload.get("latency_ms")
        lat_str = f" lat={lat}ms" if lat is not None else ""
        return f"{payload['metric']}={payload['value']} {payload.get('unit', '')}{lat_str}"
    # SNMP trap: event_type + source IP
    if "event_type" in payload:
        ip = payload.get("source_ip", "")
        return f"{payload['event_type']} from {ip}".strip()
    # Reachability: state transition
    if "state" in payload and "previous_state" in payload:
        return f"{payload['previous_state']}→{payload['state']} loss={payload.get('loss_pct', '?')}%"
    # Fallback — short JSON dump.
    return json.dumps(payload, default=str)[:120]


# ──────────────────────────────────────────────────────────────────────────
# Response validation
# ──────────────────────────────────────────────────────────────────────────
def parse_response(raw_text: str) -> dict[str, Any]:
    """Parse and validate Claude's JSON response.

    Tolerant of stray whitespace + markdown fences (some models still
    add them despite explicit instructions). Raises ValueError on a
    response that doesn't match the schema.
    """
    text = raw_text.strip()
    # Strip optional ```json fences.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"RCA response was not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("RCA response was not a JSON object")

    missing = RESPONSE_SCHEMA_KEYS - data.keys()
    if missing:
        raise ValueError(f"RCA response missing required keys: {missing}")

    if data["severity"] not in VALID_SEVERITIES:
        raise ValueError(f"RCA response has invalid severity: {data['severity']!r}")

    try:
        conf = float(data["confidence"])
    except (TypeError, ValueError) as e:
        raise ValueError(f"RCA confidence not numeric: {data['confidence']!r}") from e
    if not (0.0 <= conf <= 1.0):
        raise ValueError(f"RCA confidence out of range [0,1]: {conf}")
    data["confidence"] = conf

    if not isinstance(data["evidence"], list):
        raise ValueError("RCA evidence must be an array")
    if not isinstance(data["supporting_assets"], list):
        raise ValueError("RCA supporting_assets must be an array")

    # Drop any extra keys to keep the audit record clean.
    return {k: data[k] for k in RESPONSE_SCHEMA_KEYS}
