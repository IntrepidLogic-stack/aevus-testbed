"""Tests for infra/lambda/rca/context.py — chattering extraction (Task #128).

context.gather() itself is integration-heavy (S3 + SiteWise) and tested
via the deployed Lambda's CloudWatch logs. _extract_chattering is a pure
function — exactly the surface that benefits from unit tests, since it
parses a string format that the alert engine emits and could drift.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# context.py imports boto3 at module-load time. test_rca_handler.py also
# stubs boto3 BEFORE its first handler import — but only if boto3 isn't
# already in sys.modules. If the real boto3 has been loaded by anyone
# (e.g. a prior context import), the handler tests then fail with
# NoRegionError. Mirror handler's stub here so context can load without
# the real AWS SDK regardless of test order.
if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *a, **k: MagicMock(name=f"{a[0] if a else 'unknown'}-mock")
    sys.modules["boto3"] = boto3_stub
if "botocore" not in sys.modules:
    botocore = types.ModuleType("botocore")
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = lambda **kw: MagicMock(name="Config-mock")
    botocore_exceptions = types.ModuleType("botocore.exceptions")

    class _FakeClientError(Exception):
        pass

    class _FakeBotoCoreError(Exception):
        pass

    botocore_exceptions.ClientError = _FakeClientError
    botocore_exceptions.BotoCoreError = _FakeBotoCoreError
    sys.modules["botocore"] = botocore
    # Include botocore.config — handler.py imports Config from it. If
    # test_rca_handler.py runs second, it sees "botocore" in sys.modules
    # and skips its own stub setup, so we must register all submodules
    # handler.py depends on here too.
    sys.modules["botocore.config"] = botocore_config
    sys.modules["botocore.exceptions"] = botocore_exceptions

# Same import dance as test_rca_prompt.py — make the Lambda dir importable.
RCA_DIR = Path(__file__).parent.parent.parent / "infra" / "lambda" / "rca"
sys.path.insert(0, str(RCA_DIR))

from context import _extract_chattering  # noqa: E402


def _chat_event(metric: str, ts: str, asset_id: str = "RTU-01", alert_id: str | None = None) -> dict:
    """Build an event matching the shape AlertEngine emits via MQTT → S3 audit.

    Mirrors src/engine/alert_engine.py _record_fire_and_check_chattering output:
      id = "CHAT-<8hex>"
      severity = "warning"
      message = "{asset_name}: {metric_label} chattering (N fires in M min) — ..."
    """
    aid = alert_id or "CHAT-" + ("A" * 8)
    return {
        "ts": ts,
        "type": "alert",
        "source": "alert_engine",
        "asset_id": asset_id,
        "payload": {
            "id": aid,
            "severity": "warning",
            "asset_id": asset_id,
            "asset_name": "SCADAPack 470",
            "message": f"SCADAPack 470: {metric} chattering (7 fires in 10 min) — auto-shelved for 30 min (ISA-18.2 §7.5)",
            "detected_at": ts,
            "status": "open",
        },
    }


def _normal_event(metric: str, value: float, ts: str) -> dict:
    """A regular threshold-fire event, NOT chattering."""
    return {
        "ts": ts,
        "type": "event",
        "source": "modbus",
        "payload": {"metric": metric, "value": value, "unit": "PSI"},
    }


def test_empty_events_returns_empty():
    assert _extract_chattering([]) == []


def test_no_chattering_events_returns_empty():
    """An event window full of normal threshold alarms must not be
    confused for chattering."""
    events = [
        _normal_event("discharge_pressure", 1180, "2026-05-20T14:30:00Z"),
        _normal_event("discharge_pressure", 1442, "2026-05-20T14:32:00Z"),
    ]
    assert _extract_chattering(events) == []


def test_detects_chattering_by_alert_id_prefix():
    """The CHAT- ID prefix alone is enough — robust against message format
    drift in AlertEngine."""
    events = [_chat_event("vibration", "2026-05-20T14:30:00Z")]
    result = _extract_chattering(events)
    assert len(result) == 1
    assert result[0]["metric"] == "vibration"
    assert result[0]["asset_id"] == "RTU-01"


def test_extracts_metric_from_message():
    """The metric should be the substring between '{asset_name}: ' and
    ' chattering' — that's the format AlertEngine emits."""
    events = [_chat_event("high_pressure_alarm", "2026-05-20T14:30:00Z")]
    result = _extract_chattering(events)
    assert result[0]["metric"] == "high_pressure_alarm"


def test_dedupes_per_metric_keeping_latest():
    """If a metric chatters, recovers, then chatters again in the window,
    keep only the most recent record — older meta-alarms add no signal."""
    events = [
        _chat_event("rssi", "2026-05-20T14:00:00Z", alert_id="CHAT-OLDESTXX"),
        _chat_event("rssi", "2026-05-20T14:15:00Z", alert_id="CHAT-MIDXXXXX"),
        _chat_event("rssi", "2026-05-20T14:30:00Z", alert_id="CHAT-NEWESTXX"),
    ]
    result = _extract_chattering(events)
    assert len(result) == 1
    assert result[0]["id"] == "CHAT-NEWESTXX"


def test_multiple_metrics_returned_chronologically():
    """Two different metrics chattering should both appear, oldest-first
    (matches how _render_events / the prompt expect to read context)."""
    events = [
        _chat_event("rssi", "2026-05-20T14:00:00Z"),
        _normal_event("discharge_pressure", 1180, "2026-05-20T14:10:00Z"),
        _chat_event("temperature", "2026-05-20T14:20:00Z"),
    ]
    result = _extract_chattering(events)
    assert len(result) == 2
    metrics = [r["metric"] for r in result]
    assert metrics == ["rssi", "temperature"]


def test_handles_missing_payload_gracefully():
    """If an event has neither 'payload' nor a top-level 'id' looking like
    a CHAT alert, we must not crash and must not detect chattering."""
    events = [{"ts": "2026-05-20T14:00:00Z", "type": "event"}]
    assert _extract_chattering(events) == []


def test_detects_via_message_only_when_id_missing():
    """Backstop heuristic — if AlertEngine changes the ID format but keeps
    'chattering' in the message, we still detect it."""
    events = [
        {
            "ts": "2026-05-20T14:00:00Z",
            "type": "alert",
            "asset_id": "RAD-01",
            "payload": {
                "id": "ALT-MOOPHAH1",  # not a CHAT prefix
                "asset_id": "RAD-01",
                "message": "Trio JR900: snr chattering (5 fires in 10 min) — ...",
            },
        }
    ]
    result = _extract_chattering(events)
    assert len(result) == 1
    assert result[0]["metric"] == "snr"
