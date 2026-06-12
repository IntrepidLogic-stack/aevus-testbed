"""Tests for the alert-flood defenses (Task #201).

The platform that sells ISA-18.2 alarm rationalization must not flood its
own operator's inbox. These tests lock in the three defenses:
  1. severity gate — only CRITICAL emails in real time
  2. condition-keyed dedup — flapping UUIDs don't defeat the rate limit
  3. global circuit breaker — hard hourly cap
plus the WARNING digest batching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.engine import notifier as notifier_mod
from src.engine.notifier import NotificationEngine, _condition_key, _value_range
from src.models.alert import Alert


def _alert(severity="warning", asset_id="RAD-01", message="RSSI low", alert_id=None):
    import uuid

    return Alert(
        id=alert_id or f"ALT-{uuid.uuid4().hex[:8].upper()}",
        severity=severity,
        asset_id=asset_id,
        asset_name=asset_id,
        message=message,
        detected_at=datetime.now(UTC),
        status="open",
    )


@pytest.fixture
def engine():
    with (
        patch("src.engine.notifier.boto3"),
        patch.object(notifier_mod.settings, "notifications_enabled", True),
        patch.object(notifier_mod.settings, "notification_email_to", "woody@intrepidlogic.io"),
        patch.object(notifier_mod.settings, "notification_sms_to", ""),
    ):
        eng = NotificationEngine()
        eng._send_email = AsyncMock()
        eng._send_sms = AsyncMock()
        eng._send_digest = AsyncMock()
        yield eng


class TestSeverityGate:
    @pytest.mark.asyncio
    async def test_warning_does_not_email(self, engine):
        await engine.notify(_alert(severity="warning"))
        engine._send_email.assert_not_called()
        assert len(engine._warning_digest) == 1

    @pytest.mark.asyncio
    async def test_info_does_not_email(self, engine):
        await engine.notify(_alert(severity="info"))
        engine._send_email.assert_not_called()
        assert len(engine._warning_digest) == 1

    @pytest.mark.asyncio
    async def test_critical_emails(self, engine):
        await engine.notify(_alert(severity="critical"))
        engine._send_email.assert_called_once()


class TestConditionDedup:
    @pytest.mark.asyncio
    async def test_flapping_critical_with_fresh_uuids_deduped(self, engine):
        """The bug: each flap had a new alert.id, defeating the rate limit.
        Now keyed on condition — only the first fires."""
        for _ in range(5):
            # Same asset+severity+message, fresh UUID each time (the flap)
            await engine.notify(_alert(severity="critical", message="RSSI critical"))
        engine._send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_conditions_each_email(self, engine):
        await engine.notify(_alert(severity="critical", asset_id="RAD-01", message="A"))
        await engine.notify(_alert(severity="critical", asset_id="RAD-02", message="B"))
        assert engine._send_email.call_count == 2

    def test_condition_key_ignores_uuid(self):
        a1 = _alert(severity="critical", message="X", alert_id="ALT-AAAA")
        a2 = _alert(severity="critical", message="X", alert_id="ALT-BBBB")
        assert _condition_key(a1) == _condition_key(a2)


class TestGlobalCap:
    @pytest.mark.asyncio
    async def test_hourly_cap_blocks_excess(self, engine):
        """Past the global cap, even distinct critical conditions are dropped."""
        for i in range(notifier_mod.GLOBAL_EMAIL_CAP_PER_HOUR + 3):
            await engine.notify(_alert(severity="critical", asset_id=f"AST-{i}", message=f"m{i}"))
        # Only up to the cap should have emailed
        assert engine._send_email.call_count == notifier_mod.GLOBAL_EMAIL_CAP_PER_HOUR


class TestDigest:
    @pytest.mark.asyncio
    async def test_flush_sends_one_digest(self, engine):
        for _ in range(10):
            await engine.notify(_alert(severity="warning"))
        assert len(engine._warning_digest) == 10
        await engine.flush_warning_digest()
        engine._send_digest.assert_called_once()
        assert len(engine._warning_digest) == 0

    @pytest.mark.asyncio
    async def test_flush_empty_is_noop(self, engine):
        await engine.flush_warning_digest()
        engine._send_digest.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_clears_without_sending(self, engine):
        engine._warning_digest = [_alert(severity="warning")]
        with patch.object(notifier_mod.settings, "notifications_enabled", False):
            await engine.flush_warning_digest()
        engine._send_digest.assert_not_called()
        assert len(engine._warning_digest) == 0


class TestValueInsensitiveDedup:
    """Task #243: a vital oscillating near its threshold is ONE condition,
    not one condition per distinct reading."""

    def test_condition_key_ignores_reading_value(self):
        a1 = _alert(message="SCADAPack 470: VIBRATION warning at 5.27 mm/s")
        a2 = _alert(message="SCADAPack 470: VIBRATION warning at 4.64 mm/s")
        assert _condition_key(a1) == _condition_key(a2)

    def test_condition_key_separates_metrics(self):
        a1 = _alert(message="SCADAPack 470: VIBRATION warning at 5.27 mm/s")
        a2 = _alert(message="SCADAPack 470: BATTERY VOLTAGE warning at 11.8 VDC")
        assert _condition_key(a1) != _condition_key(a2)

    @pytest.mark.asyncio
    async def test_flapping_values_collapse_to_one_digest_row(self, engine):
        """The flood: 9 vibration warnings at 9 slightly-different values
        rendered as 9 'conditions'. Now they are one group of 9."""
        for v in (5.27, 4.64, 4.62, 4.55, 4.69, 5.21, 4.53, 4.58, 4.50):
            await engine.notify(_alert(message=f"SCADAPack 470: VIBRATION warning at {v} mm/s"))
        await engine.flush_warning_digest()
        new_groups = engine._send_digest.call_args.args[0]
        assert len(new_groups) == 1
        assert len(next(iter(new_groups.values()))) == 9

    @pytest.mark.asyncio
    async def test_critical_value_jitter_does_not_bypass_cooldown(self, engine):
        """Value-sensitive keys let 945 PSI then 946 PSI send two critical
        emails inside the cooldown window. Now they dedup."""
        await engine.notify(_alert(severity="critical", message="Suction pressure critical: 945 PSI"))
        await engine.notify(_alert(severity="critical", message="Suction pressure critical: 946 PSI"))
        engine._send_email.assert_called_once()

    def test_value_range_renders_spread(self):
        group = [
            _alert(message="VIBRATION warning at 4.5 mm/s"),
            _alert(message="VIBRATION warning at 5.27 mm/s"),
            _alert(message="VIBRATION warning at 4.64 mm/s"),
        ]
        assert _value_range(group) == " (4.5–5.27)"

    def test_value_range_empty_for_single_value(self):
        group = [_alert(message="VIBRATION warning at 4.5 mm/s")] * 3
        assert _value_range(group) == ""


class TestSteadyStateSuppression:
    """Task #243: report a condition on ENTRY; while it stays continuously
    active, later digests suppress it (down to a summary line / no email)."""

    @pytest.mark.asyncio
    async def test_second_flush_of_same_condition_sends_nothing(self, engine):
        await engine.notify(_alert(message="VIBRATION warning at 4.6 mm/s"))
        await engine.flush_warning_digest()
        assert engine._send_digest.call_count == 1
        # Same condition keeps flapping into the next window…
        await engine.notify(_alert(message="VIBRATION warning at 4.8 mm/s"))
        await engine.flush_warning_digest()
        # …but it was already reported: no second email at all.
        assert engine._send_digest.call_count == 1

    @pytest.mark.asyncio
    async def test_new_condition_still_reported_alongside_steady(self, engine):
        await engine.notify(_alert(message="VIBRATION warning at 4.6 mm/s"))
        await engine.flush_warning_digest()
        await engine.notify(_alert(message="VIBRATION warning at 4.8 mm/s"))
        await engine.notify(_alert(asset_id="RAD-02", message="SNR warning at 12 dB"))
        await engine.flush_warning_digest()
        assert engine._send_digest.call_count == 2
        new_groups, ongoing_groups = engine._send_digest.call_args.args
        assert len(new_groups) == 1  # only the SNR condition is new
        assert len(ongoing_groups) == 1  # vibration is steady-state

    @pytest.mark.asyncio
    async def test_condition_reports_again_after_quiet_ttl(self, engine):
        await engine.notify(_alert(message="VIBRATION warning at 4.6 mm/s"))
        await engine.flush_warning_digest()
        # Age the steady-state entry past the TTL (condition went quiet).
        key = next(iter(engine._reported_conditions))
        engine._reported_conditions[key] -= notifier_mod.settings.warning_digest_steady_ttl + 1
        await engine.notify(_alert(message="VIBRATION warning at 4.7 mm/s"))
        await engine.flush_warning_digest()
        assert engine._send_digest.call_count == 2  # re-entry → reported again


class TestLlmSummary:
    @pytest.mark.asyncio
    async def test_off_by_default_no_bedrock_call(self, engine):
        groups = {"k": [_alert(message="VIBRATION warning at 4.6 mm/s")]}
        assert await engine._llm_summary(groups, {}) == ""
        assert not hasattr(engine, "_bedrock")
