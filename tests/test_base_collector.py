"""Tests for BaseCollector."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.collectors.base import BaseCollector


class ConcreteCollector(BaseCollector):
    """Concrete implementation for testing."""

    async def poll(self):
        return [self._make_reading(metric="test", value=42.0, unit="x", source="test")]

    async def is_reachable(self):
        return True


@pytest.fixture
def collector():
    return ConcreteCollector(asset_id="TEST-01", host="10.0.0.1", poll_interval=30)


class TestBaseCollector:
    def test_init(self, collector):
        assert collector.asset_id == "TEST-01"
        assert collector.host == "10.0.0.1"
        assert collector.poll_interval == 30

    @pytest.mark.asyncio
    async def test_poll_returns_readings(self, collector):
        readings = await collector.poll()
        assert len(readings) == 1
        assert readings[0].metric == "test"
        assert readings[0].value == 42.0

    @pytest.mark.asyncio
    async def test_is_reachable(self, collector):
        assert await collector.is_reachable() is True

    def test_make_reading(self, collector):
        r = collector._make_reading(metric="cpu", value=55.0, unit="%", source="snmp")
        assert r.asset_id == "TEST-01"
        assert r.metric == "cpu"
        assert r.value == 55.0

    @pytest.mark.asyncio
    async def test_safe_poll_returns_readings(self, collector):
        readings = await collector.safe_poll()
        assert len(readings) == 1

    @pytest.mark.asyncio
    async def test_safe_poll_handles_exception(self, collector):
        with patch.object(collector, "poll", side_effect=Exception("boom")):
            readings = await collector.safe_poll()
            assert readings == []
