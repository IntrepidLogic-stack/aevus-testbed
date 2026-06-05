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
        assert len(body["nodes"]) == 15  # 10 process + HTR/RTU/PWR + SOL/COM (2026-06-04)
        assert len(body["edges"]) == 8  # WH->HTR->SEP routed through the line heater (2026-06-05)
        # the new support/process assets are present
        ids = {n["id"] for n in body["nodes"]}
        assert {"HTR", "RTU", "PWR", "SOL", "COM"} <= ids
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
        assert len(body["segments"]) == 8  # WH->HTR->SEP reroute (2026-06-05)
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


class TestTwinProcess:
    """The Maps-page process strip snapshot (simulated, demo-only, coherent)."""

    def test_process_shape_and_stages(self, client):
        resp = client.get("/api/v1/twin/facility/killdeer/process")
        assert resp.status_code == 200
        body = resp.json()
        assert body["facility_id"] == "killdeer-bluejay-1"
        ids = [s["id"] for s in body["stages"]]
        assert ids == ["wellhead", "separator", "compressor", "tankfarm", "metering"]
        # sales summary carries the *oil* rate (not gas mislabeled as BOPD)
        assert set(body["sales"]) >= {"oil_bopd", "gas_mcfd", "water_bwpd"}

    def test_process_values_physically_consistent(self, client):
        body = client.get("/api/v1/twin/facility/killdeer/process").json()
        rd = {s["id"]: {r["label"]: r["value"] for r in s["readings"]} for s in body["stages"]}
        # casing pressure exceeds tubing; discharge exceeds suction
        assert rd["wellhead"]["CSG"] > rd["wellhead"]["TBG"]
        assert rd["compressor"]["DISCH"] > rd["compressor"]["SUCT"]
        # oil rate is realistic for a well (tens of BOPD), NOT the gas MCFD (~4)
        assert 20.0 <= body["sales"]["oil_bopd"] <= 120.0
        assert 1.0 <= body["sales"]["gas_mcfd"] <= 12.0
        assert body["sales"]["oil_bopd"] != body["sales"]["gas_mcfd"]
        # water rate ties to oil rate via water cut (mass balance, > 0)
        assert body["sales"]["water_bwpd"] > 0

    def test_process_unknown_facility_404(self, client):
        assert client.get("/api/v1/twin/facility/nope/process").status_code == 404
