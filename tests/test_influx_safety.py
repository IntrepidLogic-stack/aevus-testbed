"""Flux-injection guard tests for the Influx storage layer (M5).

query_latest / query_trend interpolate asset_id + metric into Flux source;
these tests pin the identifier allowlist: legit identifiers still query,
injection payloads are rejected before the query API is ever called.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.storage.influx import InfluxStorage


@pytest.fixture
def store():
    s = InfluxStorage()  # constructor builds the client lazily; no network I/O
    s._query_api = MagicMock()
    s._query_api.query.return_value = []
    return s


class TestIdentifierGuard:
    def test_valid_identifiers_query(self, store):
        store.query_trend("RAD-01", "battery_voltage", hours=24)
        assert store._query_api.query.called
        q = store._query_api.query.call_args[0][0]
        assert 'r["asset_id"] == "RAD-01"' in q
        assert 'r["metric"] == "battery_voltage"' in q

    def test_dotted_and_colon_idents_allowed(self, store):
        store.query_latest("CMP-KILLDEER")
        store.query_trend("edge.pi:01", "cpu_load_1min")
        assert store._query_api.query.call_count == 2

    @pytest.mark.parametrize(
        "evil",
        [
            'x") or true) |> yield() //',  # classic breakout
            'a" and r["secret"] == "1',  # quote injection
            "a\nb",  # newline
            'a\\"b',  # escaped quote
            "",  # empty
        ],
    )
    def test_injection_asset_id_rejected(self, store, evil):
        assert store.query_latest(evil) == []
        assert store.query_trend(evil, "rssi") == []
        assert not store._query_api.query.called

    def test_injection_metric_rejected(self, store):
        assert store.query_trend("RAD-01", 'rssi") |> drop() //') == []
        assert not store._query_api.query.called

    def test_hours_coerced_and_clamped(self, store):
        store.query_trend("RAD-01", "rssi", hours="24")  # numeric string ok
        q = store._query_api.query.call_args[0][0]
        assert "range(start: -24h)" in q
        store.query_trend("RAD-01", "rssi", hours=999999)  # clamped to 1y
        q = store._query_api.query.call_args[0][0]
        assert "range(start: -8760h)" in q

    def test_hours_non_numeric_rejected(self, store):
        assert store.query_trend("RAD-01", "rssi", hours="1h) |> evil(") == []
