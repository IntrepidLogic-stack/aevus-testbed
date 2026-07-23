"""Tests for poll-cycle evidence exposure (P3 contract #2)."""

from unittest.mock import MagicMock

from src.collectors.simulator import SimulatorCollector
from src.scheduler import PollScheduler


def _scheduler_with_collector() -> tuple[PollScheduler, SimulatorCollector]:
    sched = PollScheduler(db=MagicMock(), influx=MagicMock(), alert_engine=MagicMock())
    collector = SimulatorCollector(asset_id="RAD-01", device_type="radio", poll_interval=30)
    sched.register("RAD-01", collector)
    return sched, collector


class TestPollEvidence:
    def test_unknown_asset_returns_none(self):
        sched, _ = _scheduler_with_collector()
        assert sched.poll_evidence("NOPE-99") is None

    def test_before_first_poll(self):
        sched, _ = _scheduler_with_collector()
        ev = sched.poll_evidence("RAD-01")
        assert ev is not None
        assert ev["interval_s"] == 30
        assert ev["success_pct"] is None  # no samples yet — honest, not 100%
        assert ev["consecutive_misses"] == 0
        assert ev["last_good"] is None
        assert ev["samples"] == 0

    def test_counters_flow_through(self):
        sched, collector = _scheduler_with_collector()
        collector.poll_count = 10
        collector.poll_success_count = 9
        collector.consecutive_failures = 1
        ev = sched.poll_evidence("RAD-01")
        assert ev["success_pct"] == 90.0
        assert ev["consecutive_misses"] == 1
        assert ev["samples"] == 10
