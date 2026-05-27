"""Tests for MaintenanceTracker — run-hours boundary crossing detection."""

import pytest

from src.engine.maintenance_tracker import (
    DEFAULT_INTERVAL_HOURS,
    MaintenanceDue,
    MaintenanceTracker,
)


class _MemDB:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def get_runhours_baseline(self, asset_id: str) -> int | None:
        return self.store.get(asset_id)

    def set_runhours_baseline(self, asset_id: str, run_hours: int) -> None:
        self.store[asset_id] = run_hours


class TestConstruction:
    def test_default_interval(self):
        t = MaintenanceTracker()
        assert t.interval_hours == DEFAULT_INTERVAL_HOURS == 500

    def test_custom_interval(self):
        t = MaintenanceTracker(interval_hours=250)
        assert t.interval_hours == 250

    def test_invalid_interval_rejected(self):
        with pytest.raises(ValueError):
            MaintenanceTracker(interval_hours=0)
        with pytest.raises(ValueError):
            MaintenanceTracker(interval_hours=-50)


class TestFirstObservation:
    def test_first_check_seeds_silently(self):
        t = MaintenanceTracker(interval_hours=500)
        event = t.check("RTU-01", "SCADAPack 470", 1473)
        assert event is None
        assert t.baseline("RTU-01") == 1473

    def test_first_check_negative_rejected(self):
        t = MaintenanceTracker()
        event = t.check("RTU-01", "SCADAPack 470", -1)
        assert event is None
        assert t.baseline("RTU-01") is None


class TestBoundaryCrossing:
    def test_no_boundary_no_event(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 100)
        event = t.check("RTU-01", "SCADAPack 470", 450)
        assert event is None
        assert t.baseline("RTU-01") == 450

    def test_single_boundary_emits_event(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        event = t.check("RTU-01", "SCADAPack 470", 501)
        assert isinstance(event, MaintenanceDue)
        assert event.boundary_crossed == 500
        assert event.boundaries_in_jump == 1
        assert event.run_hours == 501
        assert event.interval_hours == 500

    def test_boundary_at_exact_multiple(self):
        """Run-hours == boundary should fire (we're 'at or above')."""
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        event = t.check("RTU-01", "SCADAPack 470", 500)
        assert event is not None
        assert event.boundary_crossed == 500

    def test_second_boundary_after_first(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        e1 = t.check("RTU-01", "SCADAPack 470", 510)
        e2 = t.check("RTU-01", "SCADAPack 470", 1001)
        assert e1.boundary_crossed == 500
        assert e2.boundary_crossed == 1000

    def test_no_double_fire_at_same_boundary(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        e1 = t.check("RTU-01", "SCADAPack 470", 510)
        e2 = t.check("RTU-01", "SCADAPack 470", 520)  # still in [500, 1000) band
        assert e1 is not None
        assert e2 is None

    def test_multi_boundary_jump_one_event(self):
        """Asset offline catches up to 1801h from 320h baseline → 500, 1000, 1500 all crossed.
        Emit one event referencing the latest boundary with boundaries_in_jump=3."""
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 320)
        event = t.check("RTU-01", "SCADAPack 470", 1801)
        assert event is not None
        assert event.boundary_crossed == 1500
        assert event.boundaries_in_jump == 3
        assert "intervals crossed in one read" in event.to_message()

    def test_no_boundary_inside_same_band(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 720)
        event = t.check("RTU-01", "SCADAPack 470", 980)
        assert event is None


class TestCounterReset:
    def test_counter_reset_re_seeds_silently(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 5_400)
        # Counter wiped during service swap → drops to 0
        event = t.check("RTU-01", "SCADAPack 470", 0)
        assert event is None
        assert t.baseline("RTU-01") == 0

    def test_small_backwards_drift_within_tolerance_noop(self):
        """1-2h backwards drift = clock/poll-jitter — do nothing."""
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 1500)
        event = t.check("RTU-01", "SCADAPack 470", 1498)
        assert event is None
        # Baseline NOT updated when value goes backwards inside tolerance
        assert t.baseline("RTU-01") == 1500

    def test_large_backwards_drift_treated_as_reset(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 5_400)
        event = t.check("RTU-01", "SCADAPack 470", 100)  # well beyond tolerance
        assert event is None
        assert t.baseline("RTU-01") == 100


class TestPerAssetIntervalOverride:
    def test_pump_at_250h_interval(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("PUMP-A", "Booster Pump", 245, interval_hours_override=250)
        event = t.check("PUMP-A", "Booster Pump", 260, interval_hours_override=250)
        assert event is not None
        assert event.boundary_crossed == 250
        assert event.interval_hours == 250

    def test_invalid_override_rejected(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("PUMP-A", "Booster", 100)
        with pytest.raises(ValueError):
            t.check("PUMP-A", "Booster", 200, interval_hours_override=0)


class TestMultipleAssetsIndependent:
    def test_two_assets_isolated(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        t.check("RTU-02", "SCADAPack 470", 499)
        e1 = t.check("RTU-01", "SCADAPack 470", 510)
        e2 = t.check("RTU-02", "SCADAPack 470", 510)
        assert e1 is not None
        assert e2 is not None
        assert e1.asset_id == "RTU-01"
        assert e2.asset_id == "RTU-02"


class TestMessageFormatting:
    def test_single_boundary_message(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 499)
        event = t.check("RTU-01", "SCADAPack 470", 503)
        msg = event.to_message()
        assert "SCADAPack 470" in msg
        assert "500" in msg
        assert "503" in msg

    def test_multi_boundary_message_mentions_catch_up(self):
        t = MaintenanceTracker(interval_hours=500)
        t.check("RTU-01", "SCADAPack 470", 100)
        event = t.check("RTU-01", "SCADAPack 470", 2050)
        assert "catch-up" in event.to_message().lower()


class TestPersistence:
    def test_db_seeded_baseline_persists_through_restart(self):
        db = _MemDB()
        db.store["RTU-01"] = 1497
        t = MaintenanceTracker(interval_hours=500, db=db)
        event = t.check("RTU-01", "SCADAPack 470", 1502)
        assert event is not None
        assert event.boundary_crossed == 1500
        assert db.store["RTU-01"] == 1502  # write-through

    def test_db_writes_through_on_seed(self):
        db = _MemDB()
        t = MaintenanceTracker(db=db)
        t.check("RTU-01", "SCADAPack 470", 800)
        assert db.store["RTU-01"] == 800

    def test_reset_clears_persistence(self):
        db = _MemDB()
        t = MaintenanceTracker(db=db)
        t.check("RTU-01", "SCADAPack 470", 5400)
        t.reset("RTU-01")
        assert t.baseline("RTU-01") is None
        assert db.store.get("RTU-01", 0) == 0
