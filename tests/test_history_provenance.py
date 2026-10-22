"""Product-integrity tests: measured history never serves simulator/reference points.

The scheduler falls back to SimulatorCollector (source="simulator") when a real
collector returns nothing, and REFERENCE_ASSETS_ENABLED injects source="reference"
replay frames. Both land in the same Influx bucket. These tests pin that:

  * every measured-history query carries the provenance filter, BEFORE
    aggregateWindow (a bucket mean can never blend real + non-real samples);
  * a simulator/reference-tagged point is excluded from the history endpoints;
  * the synthetic/demo path still works, explicitly opt-in and labeled simulated.

No real Influx is contacted: a fake query API evaluates the generated
``r["source"]`` predicate against canned tagged records.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.storage.influx import (
    NON_MEASURED_SOURCES,
    InfluxStorage,
    _provenance_filter,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
FROM_ISO = "2026-10-01T00:00:00Z"
TO_ISO = "2026-10-02T00:00:00Z"

# (asset_id, metric, source, value). RAD-01 is real; RAD-SIM only ever has fallback data.
POINTS = [
    ("RAD-01", "rssi", "snmp", -60.0),
    ("RAD-01", "rssi", "simulator", -40.0),  # fallback sample for the same asset
    ("RAD-01", "snr", "snmp", 30.0),
    ("RAD-SIM", "rssi", "simulator", -50.0),
    ("RAD-REF", "rssi", "reference", -55.0),
    ("RAD-UNTAGGED", "rssi", None, -70.0),  # no source tag -> no synthetic marker
]


def _record(asset_id: str, metric: str, value: float) -> SimpleNamespace:
    return SimpleNamespace(
        values={"asset_id": asset_id, "metric": metric, "unit": "dBm"},
        get_value=lambda: value,
        get_time=lambda: T0,
    )


class FakeQueryAPI:
    """Evaluates the generated provenance predicate against POINTS."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, query: str, org: str | None = None):
        self.queries.append(query)
        m = re.search(r'\|> filter\(fn: \(r\) => (r\["source"\][^\n]*)\)\n', query)
        assert m, "provenance filter missing from Flux query"
        pred = m.group(1)
        negative = "!=" in pred
        listed = set(re.findall(r'"(\w+)"', pred))
        rows = []
        for aid, metric, src, val in POINTS:
            keep = src not in listed if negative else src in listed  # missing tag (None) passes `!=`
            if keep:
                rows.append(_record(aid, metric, val))
        return [SimpleNamespace(records=rows)]


@pytest.fixture
def store():
    s = InfluxStorage()
    s._query_api = FakeQueryAPI()
    return s


class TestFluxFilter:
    def test_measured_filter_denies_every_non_measured_source(self):
        f = _provenance_filter()
        for src in NON_MEASURED_SOURCES:
            assert f'r["source"] != "{src}"' in f
        assert " and " in f

    def test_simulated_filter_selects_only_non_measured(self):
        f = _provenance_filter("simulated")
        for src in NON_MEASURED_SOURCES:
            assert f'r["source"] == "{src}"' in f
        assert "!=" not in f

    @pytest.mark.parametrize("junk", ["", "all", 'x"] |> drop() //', None])
    def test_unknown_provenance_fails_safe_to_measured(self, junk):
        assert _provenance_filter(junk) == _provenance_filter("measured")  # type: ignore[arg-type]

    def test_non_measured_sources_cover_simulator_and_reference(self):
        assert set(NON_MEASURED_SOURCES) == {"simulator", "reference"}

    def test_every_measured_query_has_filter_before_aggregation(self, store):
        store.query_links(["RAD-01"], ["rssi"], FROM_ISO, TO_ISO, 3600)
        store.query_rssi_matrix(FROM_ISO, TO_ISO, 3600)
        store.query_trend("RAD-01", "rssi", 24)
        store.query_latest("RAD-01")
        store.retained_since()
        qs = store._query_api.queries
        assert len(qs) == 5
        for q in qs:
            assert 'r["source"] != "simulator"' in q
            assert 'r["source"] != "reference"' in q
            if "aggregateWindow" in q:
                assert q.index('r["source"]') < q.index("aggregateWindow")


class TestMeasuredQueriesExcludeNonReal:
    def test_query_links_drops_simulator_and_reference(self, store):
        out = store.query_links(["RAD-01", "RAD-SIM", "RAD-REF"], ["rssi", "snr"], FROM_ISO, TO_ISO, 3600)
        assert "RAD-SIM" not in out  # simulator-only asset: honest no-history
        assert "RAD-REF" not in out  # reference-only asset
        assert [p["v"] for p in out["RAD-01"]["rssi"]] == [-60.0]  # the -40 simulator sample is gone
        assert [p["v"] for p in out["RAD-01"]["snr"]] == [30.0]

    def test_untagged_point_is_treated_as_measured(self, store):
        out = store.query_rssi_matrix(FROM_ISO, TO_ISO, 3600)
        assert {r["asset_id"] for r in out} == {"RAD-01", "RAD-UNTAGGED"}
        assert -40.0 not in [r["v"] for r in out]

    def test_trend_default_is_measured_only(self, store):
        vals = [p["value"] for p in store.query_trend("RAD-01", "rssi", 24)]
        assert -40.0 not in vals and -60.0 in vals

    def test_trend_simulated_returns_only_synthetic(self, store):
        vals = [p["value"] for p in store.query_trend("RAD-01", "rssi", 24, provenance="simulated")]
        assert -40.0 in vals and -60.0 not in vals
        assert vals == [-40.0, -50.0, -55.0]  # the fake returns all assets; only non-measured kept


@pytest.fixture
def client():
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


@pytest.fixture
def fake_state(store):
    """app_state whose influx is the real InfluxStorage over the fake query API."""
    state = MagicMock()
    state.influx = store
    state.db.list_assets.return_value = [
        SimpleNamespace(id="RAD-01", location="Site A"),
        SimpleNamespace(id="RAD-SIM", location="Site B"),
        SimpleNamespace(id="RAD-REF", location="Site B"),
    ]
    with patch("src.main.app_state", state):
        yield state


class TestHistoryEndpoints:
    def test_links_excludes_simulator_point_and_is_labeled_measured(self, client, fake_state):
        r = client.get(
            "/api/v1/history/links",
            params={"ids": "RAD-01,RAD-SIM,RAD-REF", "metrics": "rssi,snr", "from": FROM_ISO, "to": TO_ISO},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["provenance"] == "measured"
        # (the fake query API does not apply the asset_id predicate, so RAD-UNTAGGED may appear)
        assert "RAD-SIM" not in body["series"] and "RAD-REF" not in body["series"]
        assert [p["v"] for p in body["series"]["RAD-01"]["rssi"]] == [-60.0]

    def test_rollup_ignores_simulated_links(self, client, fake_state):
        r = client.get("/api/v1/history/rollup", params={"scope": "site", "from": FROM_ISO, "to": TO_ISO})
        assert r.status_code == 200
        body = r.json()
        assert body["provenance"] == "measured"
        links = {a for g in body["groups"] for a in g["links"]}
        assert "RAD-SIM" not in links and "RAD-REF" not in links
        assert "RAD-01" in links


class TestDemoModeStillShowsSyntheticLabeled:
    def test_health_trend_default_is_measured_and_unlabeled(self, client, fake_state):
        r = client.get("/api/v1/health/trend", params={"asset_id": "RAD-01", "metric": "rssi"})
        assert r.status_code == 200
        pts = r.json()
        assert pts and all("simulated" not in p for p in pts)
        assert -40.0 not in [p["value"] for p in pts]

    def test_health_trend_simulated_is_labeled_and_exclusive(self, client, fake_state):
        r = client.get(
            "/api/v1/health/trend",
            params={"asset_id": "RAD-01", "metric": "rssi", "provenance": "simulated"},
        )
        assert r.status_code == 200
        pts = r.json()
        assert pts, "demo/synthetic mode must still return synthetic data"
        assert all(p["simulated"] is True for p in pts)
        assert -60.0 not in [p["value"] for p in pts]  # never blends real points in

    def test_fleet_trend_simulated_is_labeled(self, client, fake_state):
        r = client.get("/api/v1/health/trend", params={"metric": "rssi", "provenance": "simulated"})
        assert r.status_code == 200
        assert r.json() and all(p["simulated"] is True and "asset_id" in p for p in r.json())

    def test_bad_provenance_rejected(self, client, fake_state):
        r = client.get("/api/v1/health/trend", params={"metric": "rssi", "provenance": "everything"})
        assert r.status_code == 422
