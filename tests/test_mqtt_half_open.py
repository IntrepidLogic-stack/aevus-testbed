"""Tests for the half-open detection in MQTTPublisher (Task #151).

The 2026-05-29 outage: the Pi's MQTT client believed it was connected for
~30 minutes after the broker silently evicted the session. Every publish()
either failed quietly or hung — and the supervisor loop's `sleep(1)`
busy-wait never noticed because nothing checked link health.

These tests prove the fix:
  1. After N consecutive publish failures, the publisher marks itself
     disconnected AND fires _reconnect_signal so the supervisor tears
     down + reconnects.
  2. A single transient failure does NOT trip the reconnect — only the
     threshold count does.
  3. A publish that takes longer than mqtt_publish_timeout is treated
     as a failure (covers the "wedged TCP socket" case where publish()
     would otherwise hang forever).
  4. A successful publish resets the consecutive-failure counter (so a
     spotty link that recovers doesn't accumulate toward the threshold).
  5. The health property exposes the counter + last-success timestamp.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.integrations.mqtt_publisher import MQTTPublisher


def _publisher_with_fake_client(publish_mock: AsyncMock) -> MQTTPublisher:
    """Build a publisher with the supervisor loop bypassed.

    We don't want to exercise aiomqtt itself — we want to exercise the
    _publish() failure-counter + reconnect-signal logic in isolation.
    """
    pub = MQTTPublisher(
        broker_host="test",
        broker_port=8883,
        site_id="testlab",
        client_id="test-edge",
        tls_enabled=False,
    )
    # Pretend we're connected with a fake client that we control.
    pub._connected = True
    pub._client = type("FakeClient", (), {"publish": publish_mock})()
    return pub


@pytest.mark.asyncio
async def test_publish_success_resets_failure_counter():
    """A successful publish should clear any prior consecutive-failure count."""
    publish_mock = AsyncMock(return_value=None)
    pub = _publisher_with_fake_client(publish_mock)
    pub._consecutive_failures = 3  # simulate prior hiccups

    await pub.publish_telemetry("RTU-01", "psi", 100.0, "PSI", source="test")

    assert pub._consecutive_failures == 0
    assert pub._last_successful_publish is not None


@pytest.mark.asyncio
async def test_single_failure_does_not_trip_reconnect():
    """One bad publish should NOT mark us disconnected — only the threshold."""
    publish_mock = AsyncMock(side_effect=ConnectionError("transient"))
    pub = _publisher_with_fake_client(publish_mock)

    await pub.publish_telemetry("RTU-01", "psi", 100.0, "PSI", source="test")

    assert pub._consecutive_failures == 1
    assert pub._connected is True  # still connected
    assert not pub._reconnect_signal.is_set()


@pytest.mark.asyncio
async def test_threshold_failures_trip_reconnect(monkeypatch):
    """After mqtt_publish_failure_threshold consecutive errors, fire reconnect."""
    from src.integrations import mqtt_publisher as mod

    monkeypatch.setattr(mod.settings, "mqtt_publish_failure_threshold", 3)

    publish_mock = AsyncMock(side_effect=ConnectionError("broker silent"))
    pub = _publisher_with_fake_client(publish_mock)

    # Three failures = exactly the threshold.
    for _ in range(3):
        await pub.publish_telemetry("RTU-01", "psi", 100.0, "PSI", source="test")

    assert pub._consecutive_failures == 3
    assert pub._connected is False  # marked dead so further publishes skip
    assert pub._reconnect_signal.is_set()  # supervisor will wake + reconnect


@pytest.mark.asyncio
async def test_publish_timeout_counts_as_failure(monkeypatch):
    """A publish that hangs past mqtt_publish_timeout must be treated as a failure.

    This is THE bug from 2026-05-29: paho's publish() didn't error, it
    just blocked on a half-open socket. The asyncio.wait_for wrapper
    converts that hang into a TimeoutError we can count.
    """
    from src.integrations import mqtt_publisher as mod

    monkeypatch.setattr(mod.settings, "mqtt_publish_timeout", 0.1)
    monkeypatch.setattr(mod.settings, "mqtt_publish_failure_threshold", 2)

    async def hang(*args, **kwargs):
        await asyncio.sleep(10)  # would hang forever in prod

    pub = _publisher_with_fake_client(AsyncMock(side_effect=hang))

    await pub.publish_telemetry("RTU-01", "psi", 100.0, "PSI", source="test")
    assert pub._consecutive_failures == 1

    await pub.publish_telemetry("RTU-01", "psi", 100.0, "PSI", source="test")
    assert pub._consecutive_failures == 2
    assert pub._reconnect_signal.is_set()


@pytest.mark.asyncio
async def test_recovery_clears_counter(monkeypatch):
    """Failures followed by a success should reset toward 0, not stay armed."""
    from src.integrations import mqtt_publisher as mod

    monkeypatch.setattr(mod.settings, "mqtt_publish_failure_threshold", 5)

    publish_mock = AsyncMock(side_effect=[ConnectionError("blip"), ConnectionError("blip"), None])
    pub = _publisher_with_fake_client(publish_mock)

    await pub.publish_telemetry("A", "m", 1.0, "u", source="t")  # fail
    await pub.publish_telemetry("A", "m", 1.0, "u", source="t")  # fail
    assert pub._consecutive_failures == 2

    await pub.publish_telemetry("A", "m", 1.0, "u", source="t")  # success
    assert pub._consecutive_failures == 0
    assert not pub._reconnect_signal.is_set()


@pytest.mark.asyncio
async def test_health_property_exposes_state():
    """Health snapshot must expose the counter + last-success for ops visibility."""
    pub = _publisher_with_fake_client(AsyncMock(return_value=None))

    h = pub.health
    assert h["connected"] is True
    assert h["consecutive_publish_failures"] == 0
    assert h["last_successful_publish"] is None
    assert h["seconds_since_last_publish"] is None

    await pub.publish_telemetry("A", "m", 1.0, "u", source="t")
    h = pub.health
    assert h["last_successful_publish"] is not None
    assert h["seconds_since_last_publish"] is not None
    assert h["seconds_since_last_publish"] >= 0
