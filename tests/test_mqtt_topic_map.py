"""Unit tests for src/integrations/topic_map.py — MQTT topic generation."""

from __future__ import annotations

import pytest

from src.integrations import topic_map


class TestTelemetryTopics:
    def test_basic_shape(self):
        assert (
            topic_map.telemetry("lab", "RTU-01", "suction_pressure")
            == "aevus/lab/RTU-01/telemetry/suction_pressure"
        )

    def test_invalid_chars_in_metric_sanitized(self):
        t = topic_map.telemetry("lab", "RTU-01", "if/slash")
        assert "/" not in t.replace("aevus/lab/RTU-01/telemetry/", "")

    def test_wildcard_chars_in_asset_id_sanitized(self):
        # MQTT reserves + and # for wildcards; an asset_id containing
        # them would let a misbehaving device write to other topics.
        assert "+" not in topic_map.telemetry("lab", "RTU+01", "x")
        assert "#" not in topic_map.telemetry("lab", "RTU#01", "x")

    def test_whitespace_replaced(self):
        # Whitespace in asset names is common; MQTT allows it but most
        # tooling chokes.
        assert " " not in topic_map.telemetry("lab", "RTU 01", "x")


class TestStateTopics:
    def test_reachability(self):
        assert (
            topic_map.state("lab", "RTU-01", "reachability")
            == "aevus/lab/RTU-01/state/reachability"
        )


class TestEventTopics:
    def test_dnp3_event(self):
        assert (
            topic_map.event("lab", "RTU-01", "dnp3")
            == "aevus/lab/RTU-01/events/dnp3"
        )

    def test_snmp_trap_event(self):
        # 'snmp-trap' should be preserved (hyphen is legal in MQTT).
        assert (
            topic_map.event("lab", "SW-01", "snmp-trap")
            == "aevus/lab/SW-01/events/snmp-trap"
        )


class TestAlertTopics:
    def test_critical(self):
        assert (
            topic_map.alert("lab", "RTU-01", "critical")
            == "aevus/lab/RTU-01/alerts/critical"
        )

    def test_warning(self):
        assert (
            topic_map.alert("lab", "RTU-01", "warning")
            == "aevus/lab/RTU-01/alerts/warning"
        )


class TestSubscriptions:
    def test_all_for_site(self):
        assert topic_map.subscription_all_for_site("lab") == "aevus/lab/#"

    def test_alerts_for_site(self):
        assert (
            topic_map.subscription_alerts_for_site("lab")
            == "aevus/lab/+/alerts/+"
        )

    def test_all_critical(self):
        assert (
            topic_map.subscription_all_critical_alerts()
            == "aevus/+/+/alerts/critical"
        )


class TestTopicLeakageGuards:
    """These tests pin the topic IAM model: a misbehaving device can't
    produce a topic that overlaps another site or asset's prefix."""

    def test_evil_asset_id_cannot_climb_path(self):
        # Even if someone passes "RTU-01/../OTHER" as asset_id, the
        # sanitizer must collapse it to a single segment.
        t = topic_map.telemetry("lab", "RTU-01/../OTHER", "x")
        # All slashes are replaced with underscores in the asset_id segment.
        segments = t.split("/")
        # Should still be exactly 5 segments (aevus/site/asset/telemetry/metric).
        assert len(segments) == 5

    def test_empty_segment_replaced(self):
        t = topic_map.telemetry("lab", "", "x")
        # Empty asset_id becomes "_" — not an empty MQTT level (which
        # would collapse and let a malformed publish hit aevus/lab/x).
        assert "//" not in t
