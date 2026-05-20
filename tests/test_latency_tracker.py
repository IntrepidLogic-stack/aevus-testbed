"""Unit tests for src/integrations/latency_tracker.py.

Pins the contract that powers the patent demo metrics endpoint:
percentile accuracy, capacity-bounded rolling window, thread safety
under concurrent record/snapshot.
"""

from __future__ import annotations

import threading

import pytest

from src.integrations import latency_tracker
from src.integrations.latency_tracker import LatencyHistogram, LatencyStats


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    latency_tracker.reset_all()
    yield
    latency_tracker.reset_all()


class TestPercentiles:
    def test_empty_returns_zero(self):
        h = LatencyHistogram("test")
        s = h.snapshot()
        assert s.count == 0
        assert s.p50_ms == 0 and s.p95_ms == 0 and s.p99_ms == 0

    def test_single_sample(self):
        h = LatencyHistogram("test")
        h.record(123.4)
        s = h.snapshot()
        assert s.count == 1
        assert s.p50_ms == 123.4
        assert s.p95_ms == 123.4
        assert s.min_ms == 123.4
        assert s.max_ms == 123.4
        assert s.mean_ms == 123.4

    def test_p95_above_p50(self):
        h = LatencyHistogram("test")
        for v in range(1, 101):  # 1..100ms
            h.record(float(v))
        s = h.snapshot()
        assert s.count == 100
        # p50 is around the median.
        assert 49 <= s.p50_ms <= 51
        # p95 is somewhere above 90.
        assert s.p95_ms >= 95
        # p99 is at the very top.
        assert s.p99_ms >= 99
        assert s.min_ms == 1.0
        assert s.max_ms == 100.0

    def test_p95_for_dnp3_pattern(self):
        """Realistic DNP3 latency pattern: most events 50-200ms, a few
        outliers up to 800ms. p95 should reflect the tail."""
        h = LatencyHistogram("dnp3")
        for v in [55, 67, 72, 80, 85, 90, 95, 102, 110, 120, 145, 160, 175, 195, 220, 350, 500, 750, 800, 60]:
            h.record(v)
        s = h.snapshot()
        # p50 should be in the typical bulk (75-150ms range).
        assert 75 <= s.p50_ms <= 200
        # p95 picks up the outliers.
        assert s.p95_ms >= 350


class TestCapacityRolling:
    def test_evicts_oldest_when_full(self):
        h = LatencyHistogram("test", capacity=5)
        for v in [10, 20, 30, 40, 50, 60, 70]:
            h.record(v)
        s = h.snapshot()
        assert s.count == 5
        # The earliest two (10, 20) evicted; remaining min = 30.
        assert s.min_ms == 30
        assert s.max_ms == 70


class TestSanitization:
    def test_negative_clamps_to_zero(self):
        h = LatencyHistogram("test")
        h.record(-50)
        s = h.snapshot()
        assert s.count == 1
        assert s.min_ms == 0

    def test_nan_dropped(self):
        h = LatencyHistogram("test")
        h.record(float("nan"))
        h.record(100)
        s = h.snapshot()
        assert s.count == 1
        assert s.min_ms == 100

    def test_inf_dropped(self):
        h = LatencyHistogram("test")
        h.record(float("inf"))
        h.record(50)
        s = h.snapshot()
        assert s.count == 1


class TestModuleSingletons:
    def test_record_detection_latency_visible_in_snapshot(self):
        latency_tracker.record_detection_latency(143.0)
        latency_tracker.record_detection_latency(220.0)
        snap = latency_tracker.snapshot()
        assert snap["detection_latency_ms"]["count"] == 2
        assert snap["rca_latency_ms"]["count"] == 0

    def test_none_record_is_noop(self):
        latency_tracker.record_detection_latency(None)
        latency_tracker.record_rca_latency(None)
        snap = latency_tracker.snapshot()
        assert snap["detection_latency_ms"]["count"] == 0
        assert snap["rca_latency_ms"]["count"] == 0

    def test_rca_and_detection_are_independent(self):
        latency_tracker.record_detection_latency(100.0)
        latency_tracker.record_rca_latency(2500.0)
        snap = latency_tracker.snapshot()
        assert snap["detection_latency_ms"]["count"] == 1
        assert snap["rca_latency_ms"]["count"] == 1
        assert snap["detection_latency_ms"]["max_ms"] == 100.0
        assert snap["rca_latency_ms"]["max_ms"] == 2500.0


class TestThreadSafety:
    def test_concurrent_record_does_not_crash(self):
        """Two threads recording into the same histogram should not
        corrupt the sorted-list invariant. Sample-count must equal
        the total recorded."""
        h = LatencyHistogram("test", capacity=10_000)
        N = 500

        def writer(start: int):
            for v in range(start, start + N):
                h.record(float(v))

        t1 = threading.Thread(target=writer, args=(0,))
        t2 = threading.Thread(target=writer, args=(1000,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        s = h.snapshot()
        assert s.count == 2 * N
        # Sorted invariant: min ≤ p50 ≤ p95 ≤ p99 ≤ max.
        assert s.min_ms <= s.p50_ms <= s.p95_ms <= s.p99_ms <= s.max_ms
