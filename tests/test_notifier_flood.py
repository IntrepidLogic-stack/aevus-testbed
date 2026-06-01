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
from src.engine.notifier import NotificationEngine, _condition_key
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
