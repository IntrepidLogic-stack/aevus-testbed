"""Unit tests for the shared SNMP CLI transport mixin (H4).

These directly exercise the code de-duplicated out of the four SNMP collectors,
so the shared logic is covered even though radio/router/edge have no
collector-level tests.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.collectors.snmp_cli import SNMPCliMixin


class _FakeCollector(SNMPCliMixin):
    def __init__(self) -> None:
        self.host = "10.0.0.9"
        self.community = "public"
        self.log = SimpleNamespace(warning=lambda *a, **k: None)


@pytest.fixture
def snmp():
    return _FakeCollector()


class TestParseWalkValue:
    def test_strips_type_prefix_and_quotes(self, snmp):
        assert snmp._parse_snmp_walk_value('STRING: "eth0"') == "eth0"
        assert snmp._parse_snmp_walk_value("Gauge32: 123") == "123"
        assert snmp._parse_snmp_walk_value("Counter32: 0") == "0"
        assert snmp._parse_snmp_walk_value("INTEGER: 2") == "2"

    def test_none_and_bare(self, snmp):
        assert snmp._parse_snmp_walk_value(None) == ""
        assert snmp._parse_snmp_walk_value('"plain"') == "plain"


class TestTimeticks:
    def test_paren_format(self, snmp):
        # (360000) hundredths-of-a-second = 3600 s = 1.0 hour
        assert snmp._snmp_timeticks_to_hours("Timeticks: (360000) 1:00:00") == 1.0

    def test_bare_number(self, snmp):
        assert snmp._snmp_timeticks_to_hours("720000") == 2.0

    def test_none_and_unparseable(self, snmp):
        assert snmp._snmp_timeticks_to_hours(None) is None
        assert snmp._snmp_timeticks_to_hours("not-a-number") is None


class TestSnmpGetSync:
    @staticmethod
    def _result(returncode=0, stdout=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    def test_parses_quoted_value(self, snmp):
        with patch("subprocess.run", return_value=self._result(0, '"eth0"\n')):
            assert snmp._snmp_get_sync("1.2.3") == "eth0"

    def test_strips_type_prefix(self, snmp):
        with patch("subprocess.run", return_value=self._result(0, "STRING: value\n")):
            assert snmp._snmp_get_sync("1.2.3") == "value"

    def test_nonzero_returncode_is_none(self, snmp):
        with patch("subprocess.run", return_value=self._result(1, "")):
            assert snmp._snmp_get_sync("1.2.3") is None

    def test_timeout_is_none(self, snmp):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("snmpget", 10)):
            assert snmp._snmp_get_sync("1.2.3") is None

    def test_binary_missing_is_none(self, snmp):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert snmp._snmp_get_sync("1.2.3") is None


class TestSnmpWalkSync:
    @staticmethod
    def _result(returncode=0, stdout=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    def test_parses_oid_value_pairs(self, snmp):
        out = "IF-MIB::ifDescr.1 = STRING: eth0\nIF-MIB::ifDescr.2 = STRING: eth1\n"
        with patch("subprocess.run", return_value=self._result(0, out)):
            walk = snmp._snmp_walk_sync("1.3.6.1.2.1.2.2.1.2")
        assert walk == {
            "IF-MIB::ifDescr.1": "STRING: eth0",
            "IF-MIB::ifDescr.2": "STRING: eth1",
        }

    def test_empty_on_failure(self, snmp):
        with patch("subprocess.run", return_value=self._result(1, "")):
            assert snmp._snmp_walk_sync() == {}
