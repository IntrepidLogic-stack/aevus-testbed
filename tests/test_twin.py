"""Tests for the digital-twin binding contract (topology + flow)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app) as c:
            yield c


class TestTwinTopology:
    def test_topology_ok(self, client):
        resp = client.get("/api/v1/twin/facility/killdeer/topology")
        assert resp.status_code == 200
        body = resp.json()
        assert body["facility_id"] == "killdeer-bluejay-1"
        assert len(body["nodes"]) == 10
        assert len(body["edges"]) == 7
        # edge wire-contract uses {from, to}, not the internal field name
        e = body["edges"][0]
        assert "from" in e and "to" in e and "src" not in e
        assert e["product"] in ("oil", "gas", "water", "chemical")

    def test_topology_unknown_facility_404(self, client):
        resp = client.get("/api/v1/twin/facility/nope/topology")
        assert resp.status_code == 404


class TestTwinFlow:
    def test_flow_shape_and_bounds(self, client):
        resp = client.get("/api/v1/twin/facility/killdeer/flow")
        assert resp.status_code == 200
        body = resp.json()
        assert body["facility_id"] == "killdeer-bluejay-1"
        assert len(body["segments"]) == 7
        for s in body["segments"]:
            assert 0.0 <= s["flow"] <= 1.0  # normalized — never raw
            assert s["dir"] in (-1, 0, 1)
            assert s["status"] in ("good", "warn", "bad", "unknown")

    def test_flow_segment_ids_match_topology(self, client):
        topo = client.get("/api/v1/twin/facility/killdeer/topology").json()
        flow = client.get("/api/v1/twin/facility/killdeer/flow").json()
        assert {e["id"] for e in topo["edges"]} == {s["id"] for s in flow["segments"]}

    def test_flow_never_leaks_raw_values(self, client):
        """Trade-secret guard: the flow payload must expose only normalized
        flow + coarse status — no raw process values or scoring internals."""
        body = client.get("/api/v1/twin/facility/killdeer/flow").json()
        allowed = {"id", "product", "flow", "dir", "status"}
        for s in body["segments"]:
            assert set(s.keys()) <= allowed


class TestAskTwinContext:
    """The 'Ask the Twin' grounding snapshot (no Bedrock needed to test it)."""

    def test_context_is_grounded(self, client):
        from src.api.ai import _build_twin_context

        ctx = _build_twin_context("killdeer")
        assert "BlueJay" in ctx or "Killdeer" in ctx
        assert "flow" in ctx.lower()
        assert "Separator" in ctx  # equipment names present

    def test_context_has_no_raw_process_units(self, client):
        """Only normalized flow (0-1) may reach the model — never raw PSI/MCFD/VDC."""
        from src.api.ai import _build_twin_context

        ctx = _build_twin_context("killdeer")
        for unit in ("PSI", "MCFD", "VDC", "mm/s"):
            assert unit not in ctx

    def test_context_unknown_facility_empty(self, client):
        from src.api.ai import _build_twin_context

        assert _build_twin_context("nope") == ""
