"""Tests for infra/lambda/rca/prompt.py.

These run on the dev side — they don't call Bedrock. We pin:
  • prompt assembly is deterministic given the same context
  • missing-context cases render gracefully ("no events in window")
  • response parser tolerates markdown fences + validates schema
  • response parser rejects malformed or out-of-range output
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the Lambda source to sys.path so we can import without
# packaging it first. tests/conftest.py already inserts the repo
# root; we add the rca dir explicitly.
RCA_DIR = Path(__file__).parent.parent.parent / "infra" / "lambda" / "rca"
sys.path.insert(0, str(RCA_DIR))

from prompt import PromptContext, parse_response, render  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Render
# ──────────────────────────────────────────────────────────────────────────
def _ctx(**overrides) -> PromptContext:
    base = {
        "alert": {
            "id": "ALT-CB341B20",
            "severity": "critical",
            "asset_id": "RTU-01",
            "asset_name": "SCADAPack 470",
            "message": "SCADAPack 470: high_pressure_alarm critical at ACTIVE",
            "detected_at": "2026-05-20T14:32:05Z",
            "status": "open",
        },
        "asset": {
            "id": "RTU-01",
            "name": "SCADAPack 470",
            "type": "rtu",
            "vendor": "Schneider",
            "model": "SCADAPack 470",
            "ip_address": "192.168.88.21",
            "location": "Lab Cabinet",
            "health": 45,
            "status": "bad",
            "last_seen": "2026-05-20T14:32:05Z",
        },
        "recent_events": [
            {
                "ts": "2026-05-20T14:30:00Z",
                "type": "event",
                "event_class": "dnp3",
                "source": "dnp3",
                "payload": {"metric": "discharge_pressure", "value": 1180.0, "unit": "PSI"},
            },
            {
                "ts": "2026-05-20T14:32:05Z",
                "type": "event",
                "event_class": "dnp3",
                "source": "dnp3",
                "payload": {"metric": "high_pressure_alarm", "value": True, "unit": "bool", "latency_ms": 143},
            },
        ],
        "recent_telemetry": [
            {"ts": "2026-05-20T14:30:00Z", "metric": "discharge_pressure", "value": 1180, "unit": "PSI"},
            {"ts": "2026-05-20T14:30:30Z", "metric": "discharge_pressure", "value": 1245, "unit": "PSI"},
            {"ts": "2026-05-20T14:31:00Z", "metric": "discharge_pressure", "value": 1310, "unit": "PSI"},
            {"ts": "2026-05-20T14:31:30Z", "metric": "discharge_pressure", "value": 1385, "unit": "PSI"},
            {"ts": "2026-05-20T14:32:00Z", "metric": "discharge_pressure", "value": 1442, "unit": "PSI"},
            {"ts": "2026-05-20T14:30:00Z", "metric": "battery_voltage", "value": 13.1, "unit": "VDC"},
        ],
        "related_assets": [
            {"id": "RAD-01", "name": "Trio JR900 #1", "type": "radio", "status": "good", "health": 92},
        ],
    }
    base.update(overrides)
    return PromptContext(**base)


class TestRender:
    def test_system_prompt_contains_safety_rules(self):
        system, _ = render(_ctx())
        assert "ISA-101" in system
        assert "IEC 62443" in system
        assert "IL-9000" in system or "read-only" in system
        assert "JSON" in system

    def test_user_prompt_includes_alert_block(self):
        _, user = render(_ctx())
        assert "ALT-CB341B20" in user
        assert "high_pressure_alarm" in user
        assert "2026-05-20T14:32:05Z" in user

    def test_user_prompt_includes_asset_metadata(self):
        _, user = render(_ctx())
        assert "Schneider" in user
        assert "SCADAPack 470" in user
        assert "192.168.88.21" in user

    def test_user_prompt_summarizes_telemetry(self):
        """Many readings of the same metric should be summarized
        (count/min/max/last), not dumped row-by-row."""
        _, user = render(_ctx())
        assert "discharge_pressure" in user
        assert "count=" in user
        assert "min=" in user
        assert "max=" in user

    def test_dnp3_event_summary_includes_latency(self):
        """The latency_ms field on DNP3 events is the patent-relevant
        signal — it must reach the model."""
        _, user = render(_ctx())
        assert "lat=143ms" in user

    def test_renders_with_no_events(self):
        _, user = render(_ctx(recent_events=[]))
        assert "no events in window" in user

    def test_renders_with_no_telemetry(self):
        _, user = render(_ctx(recent_telemetry=[]))
        assert "no telemetry in window" in user

    def test_renders_with_no_related_assets(self):
        _, user = render(_ctx(related_assets=[]))
        assert "no related assets" in user

    def test_renders_with_minimal_asset_metadata(self):
        _, user = render(_ctx(asset={"id": "RTU-01"}))
        # Should not raise; should fill missing fields with '?'.
        assert "RTU-01" in user

    def test_deterministic_for_same_input(self):
        ctx = _ctx()
        s1, u1 = render(ctx)
        s2, u2 = render(ctx)
        assert s1 == s2
        assert u1 == u2

    # ──────────────────────────────────────────────────────────────────
    # Task #128 — chattering meta-alarm context
    # ──────────────────────────────────────────────────────────────────
    def test_no_chattering_renders_empty_marker(self):
        """When no chattering, the block must clearly say so — the LLM
        otherwise might wrongly assume the field is missing data."""
        _, user = render(_ctx(chattering_signals=[]))
        assert "CHATTERING SIGNALS" in user
        assert "no chattering metrics" in user

    def test_chattering_block_lists_metric_and_message(self):
        """A populated chattering signal must surface its metric + full
        message so the LLM has the fire-count + window to calibrate."""
        signal = {
            "id": "CHAT-A1B2C3D4",
            "metric": "high_pressure_alarm",
            "message": "SCADAPack 470: high_pressure_alarm chattering "
            "(7 fires in 10 min) — auto-shelved for 30 min (ISA-18.2 §7.5)",
            "detected_at": "2026-05-20T14:30:00Z",
            "asset_id": "RTU-01",
        }
        _, user = render(_ctx(chattering_signals=[signal]))
        assert "CHATTERING SIGNALS" in user
        assert "high_pressure_alarm" in user
        assert "7 fires in 10 min" in user
        assert "CHAT-A1B2C3D4" not in user  # we don't render alert IDs in chattering block — clutter

    def test_chattering_caps_at_8(self):
        """A noisy site mustn't blow the prompt budget."""
        signals = [
            {
                "id": f"CHAT-{i:08X}",
                "metric": f"metric_{i}",
                "message": f"asset: metric_{i} chattering (5 fires in 10 min) — ...",
                "detected_at": f"2026-05-20T14:{i:02d}:00Z",
                "asset_id": "RTU-01",
            }
            for i in range(15)
        ]
        _, user = render(_ctx(chattering_signals=signals))
        # First 8 rendered; remainder summarized.
        assert "metric_0" in user
        assert "metric_7" in user
        assert "7 more (truncated)" in user

    def test_system_prompt_explains_chattering_handling(self):
        """The LLM needs the rule that chattering is observability, not
        primary failure — otherwise it might cite the meta-alarm itself."""
        system, _ = render(_ctx())
        assert "chattering" in system.lower()
        assert "primary cause" in system.lower() or "primary failure" in system.lower()


# ──────────────────────────────────────────────────────────────────────────
# parse_response
# ──────────────────────────────────────────────────────────────────────────
GOOD_RESPONSE = """{
    "probable_cause": "Discharge pressure exceeded critical threshold due to downstream valve closure.",
    "evidence": [
        "discharge_pressure rose from 1180 to 1442 PSI in 2 minutes",
        "high_pressure_alarm asserted at 14:32:05Z via DNP3 (latency 143ms)",
        "asset health dropped from 92 to 45"
    ],
    "severity": "critical",
    "recommended_action": "Dispatch field technician to inspect downstream valve V-103 before any restart.",
    "confidence": 0.85,
    "supporting_assets": ["RTU-01"]
}"""


class TestParseResponse:
    def test_parses_valid_response(self):
        data = parse_response(GOOD_RESPONSE)
        assert data["probable_cause"].startswith("Discharge pressure")
        assert data["severity"] == "critical"
        assert data["confidence"] == 0.85
        assert len(data["evidence"]) == 3

    def test_tolerates_markdown_fences(self):
        wrapped = "```json\n" + GOOD_RESPONSE + "\n```"
        data = parse_response(wrapped)
        assert data["severity"] == "critical"

    def test_tolerates_bare_fences(self):
        wrapped = "```\n" + GOOD_RESPONSE + "\n```"
        data = parse_response(wrapped)
        assert data["severity"] == "critical"

    def test_strips_extra_keys(self):
        with_extra = GOOD_RESPONSE.replace(
            '"supporting_assets": ["RTU-01"]', '"supporting_assets": ["RTU-01"], "vibes": "good"'
        )
        data = parse_response(with_extra)
        assert "vibes" not in data

    def test_rejects_non_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_response("not json")

    def test_rejects_non_object(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            parse_response('["array"]')

    def test_rejects_missing_keys(self):
        bad = '{"probable_cause": "x"}'
        with pytest.raises(ValueError, match="missing required keys"):
            parse_response(bad)

    def test_rejects_invalid_severity(self):
        bad = GOOD_RESPONSE.replace('"severity": "critical"', '"severity": "bogus"')
        with pytest.raises(ValueError, match="invalid severity"):
            parse_response(bad)

    def test_rejects_out_of_range_confidence(self):
        bad = GOOD_RESPONSE.replace('"confidence": 0.85', '"confidence": 1.5')
        with pytest.raises(ValueError, match="confidence out of range"):
            parse_response(bad)

    def test_rejects_non_numeric_confidence(self):
        bad = GOOD_RESPONSE.replace('"confidence": 0.85', '"confidence": "high"')
        with pytest.raises(ValueError, match="confidence"):
            parse_response(bad)

    def test_rejects_non_list_evidence(self):
        bad = GOOD_RESPONSE.replace(
            '"evidence": [\n        "discharge_pressure rose from 1180 to 1442 PSI in 2 minutes",\n        "high_pressure_alarm asserted at 14:32:05Z via DNP3 (latency 143ms)",\n        "asset health dropped from 92 to 45"\n    ]',
            '"evidence": "single string"',
        )
        with pytest.raises(ValueError, match="evidence must be an array"):
            parse_response(bad)
