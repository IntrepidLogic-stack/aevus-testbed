"""Tests for FirmwareTracker — out-of-band firmware change detection."""

from src.engine.firmware_tracker import FirmwareChange, FirmwareTracker


class _MemDB:
    """Minimal in-memory persistence stub matching the _PersistBackend Protocol."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get_firmware_version(self, asset_id: str) -> str | None:
        return self.store.get(asset_id)

    def set_firmware_version(self, asset_id: str, version: str) -> None:
        self.store[asset_id] = version


class TestFirstObservation:
    def test_first_check_is_silent(self):
        t = FirmwareTracker()
        event = t.check("RAD-01", "Trio #1", "JR900 v6.4.2")
        assert event is None
        assert t.baseline("RAD-01") == "JR900 v6.4.2"

    def test_empty_version_ignored(self):
        t = FirmwareTracker()
        assert t.check("RAD-01", "Trio #1", "") is None
        assert t.check("RAD-01", "Trio #1", "   ") is None
        assert t.baseline("RAD-01") is None

    def test_whitespace_stripped(self):
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "  v6.4.2  ")
        assert t.baseline("RAD-01") == "v6.4.2"


class TestChangeDetection:
    def test_same_version_no_event(self):
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "v6.4.2")
        event = t.check("RAD-01", "Trio #1", "v6.4.2")
        assert event is None

    def test_different_version_emits_event(self):
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "v6.4.2")
        event = t.check("RAD-01", "Trio #1", "v6.5.0")
        assert isinstance(event, FirmwareChange)
        assert event.old_version == "v6.4.2"
        assert event.new_version == "v6.5.0"
        assert event.asset_id == "RAD-01"
        assert event.asset_name == "Trio #1"

    def test_change_message_format(self):
        t = FirmwareTracker()
        t.check("SW-01", "Catalyst 2960", "12.2(55)SE12")
        event = t.check("SW-01", "Catalyst 2960", "15.0(2)SE11")
        assert event is not None
        msg = event.to_message()
        assert "Catalyst 2960" in msg
        assert "12.2(55)SE12" in msg
        assert "15.0(2)SE11" in msg
        assert "out-of-band" in msg.lower()

    def test_baseline_updates_after_change(self):
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "v6.4.2")
        t.check("RAD-01", "Trio #1", "v6.5.0")
        assert t.baseline("RAD-01") == "v6.5.0"
        # Subsequent same-version check is now silent
        assert t.check("RAD-01", "Trio #1", "v6.5.0") is None

    def test_empty_after_baseline_is_silent(self):
        """Garbage SNMP response (empty) should not clear the baseline or alarm."""
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "v6.4.2")
        assert t.check("RAD-01", "Trio #1", "") is None
        assert t.baseline("RAD-01") == "v6.4.2"

    def test_multiple_assets_independent(self):
        t = FirmwareTracker()
        t.check("RAD-01", "Trio #1", "v6.4.2")
        t.check("RAD-02", "Trio #2", "v6.4.2")
        ev1 = t.check("RAD-01", "Trio #1", "v6.5.0")
        ev2 = t.check("RAD-02", "Trio #2", "v6.4.2")  # unchanged
        assert ev1 is not None
        assert ev2 is None


class TestPersistence:
    def test_db_seeded_baseline_loads_lazily(self):
        db = _MemDB()
        db.store["RAD-01"] = "v6.4.2"  # pre-existing baseline (e.g., service restart)
        t = FirmwareTracker(db=db)
        # First check after restart with same version should NOT fire
        event = t.check("RAD-01", "Trio #1", "v6.4.2")
        assert event is None
        # And a real change still fires
        event = t.check("RAD-01", "Trio #1", "v6.5.0")
        assert event is not None
        assert event.old_version == "v6.4.2"
        assert db.store["RAD-01"] == "v6.5.0"  # write-through

    def test_db_writes_through_on_baseline_set(self):
        db = _MemDB()
        t = FirmwareTracker(db=db)
        t.check("RAD-01", "Trio #1", "v6.4.2")
        assert db.store["RAD-01"] == "v6.4.2"

    def test_reset_clears_in_memory_and_db(self):
        db = _MemDB()
        t = FirmwareTracker(db=db)
        t.check("RAD-01", "Trio #1", "v6.4.2")
        t.reset("RAD-01")
        assert t.baseline("RAD-01") is None
        assert db.store.get("RAD-01") in (None, "")
        # Next check after reset is treated as first observation again
        assert t.check("RAD-01", "Trio #1", "v6.5.0") is None
