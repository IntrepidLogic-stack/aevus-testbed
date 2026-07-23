"""Tests for the comm-path integrity baseline (P3 contract #3)."""

from types import SimpleNamespace

from src.engine.integrity_baseline import IntegrityBaseline


def _asset(asset_id="RAD-01", source="snmp", firmware="v1.2", protocol="snmp"):
    """Minimal asset stand-in: vitals carry the source tag the baseline reads."""
    vitals = [SimpleNamespace(label="RSSI", source=source)] if source else []
    return SimpleNamespace(id=asset_id, vitals=vitals, firmware=firmware, protocol=protocol)


class TestIntegrityBaseline:
    def test_unknown_before_baseline_established(self):
        """Honest 'unknown' until MIN_SAMPLES consistent observations —
        never a false 'expected' on first sight."""
        b = IntegrityBaseline()
        a = _asset()
        b.observe(a)
        assert b.detect(a) == "unknown"  # only 1 sample

    def test_expected_after_stable_observations(self):
        b = IntegrityBaseline()
        a = _asset()
        for _ in range(3):
            b.observe(a)
        assert b.detect(a) == "expected"

    def test_protocol_deviation(self):
        """A device that switches the transport it speaks over — the
        earliest 'up but not itself' attack cue."""
        b = IntegrityBaseline()
        for _ in range(3):
            b.observe(_asset(source="snmp"))
        assert b.detect(_asset(source="modbus")) == "protocol_deviation"

    def test_config_change_on_firmware(self):
        b = IntegrityBaseline()
        for _ in range(3):
            b.observe(_asset(firmware="v1.2"))
        assert b.detect(_asset(firmware="v9.9")) == "config_change"

    def test_observe_does_not_silently_rebaseline(self):
        """A persisted change must NOT quietly become the new normal —
        else an adversary re-baselines by waiting."""
        b = IntegrityBaseline()
        for _ in range(3):
            b.observe(_asset(source="snmp"))
        deviant = _asset(source="modbus")
        for _ in range(5):
            b.observe(deviant)  # keep observing the deviation
        assert b.detect(deviant) == "protocol_deviation"  # still flagged

    def test_accept_rebaselines_after_moc(self):
        """Operator-acknowledged change (MOC) is the only path that moves
        the baseline."""
        b = IntegrityBaseline()
        for _ in range(3):
            b.observe(_asset(source="snmp"))
        deviant = _asset(source="modbus")
        b.accept("RAD-01", deviant)
        assert b.detect(deviant) == "expected"

    def test_no_id_is_unknown(self):
        b = IntegrityBaseline()
        assert b.detect(SimpleNamespace(id=None, vitals=[], firmware=None, protocol="snmp")) == "unknown"

    def test_source_falls_back_to_protocol(self):
        """Simulator-tagged vitals don't count as a real transport; the
        asset.protocol is the fallback."""
        b = IntegrityBaseline()
        a = _asset(source="simulator", protocol="dnp3")
        for _ in range(3):
            b.observe(a)
        assert b.detect(a) == "expected"  # baseline learned as dnp3
        assert b.detect(_asset(source="simulator", protocol="modbus")) == "protocol_deviation"
