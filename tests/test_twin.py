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
        assert len(body["nodes"]) == 21  # +dehy/vru/combustor/swd (audit build)
        assert len(body["edges"]) == 15  # +V3 dehy still-vent -> vapor recovery (site-walk build)
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
        assert len(body["segments"]) == 15  # +V3 dehy still-vent -> vapor recovery
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
        # full gas-train order incl. line heater + TEG dehydrator (audit build)
        assert ids == ["wellhead", "heater", "separator", "compressor", "dehydrator", "tankfarm", "metering", "flare"]
        # sales summary leads with GAS; condensate + produced water as byproducts
        assert set(body["sales"]) >= {"gas_mcfd", "condensate_bcpd", "water_bwpd"}

    def test_process_values_physically_consistent(self, client):
        body = client.get("/api/v1/twin/facility/killdeer/process").json()
        rd = {s["id"]: {r["label"]: r["value"] for r in s["readings"]} for s in body["stages"]}
        # casing pressure exceeds tubing; compressor discharge exceeds suction (boost)
        assert rd["wellhead"]["CSG"] > rd["wellhead"]["TBG"]
        assert rd["compressor"]["DISCH"] > rd["compressor"]["SUCT"]
        # flowline pressure sits BELOW tubing (pressure drops across the choke)
        assert rd["wellhead"]["FLP"] < rd["wellhead"]["TBG"]
        # 2-stage machine: interstage between suction and discharge (no impossible single-stage ratio)
        assert rd["compressor"]["SUCT"] < rd["compressor"]["INT"] < rd["compressor"]["DISCH"]
        # gas mass-balance closes: raw in = sales + fuel + flare
        bal = body["sales"]["balance"]
        assert bal["closes"] is True
        assert abs(bal["gas_in_mcfd"] - (bal["sales_mcfd"] + bal["fuel_mcfd"] + bal["flare_mcfd"])) <= 1.0

    def test_process_readings_carry_register_tags(self, client):
        """The twin↔real bridge: key points advertise their SCADAPack 470 Modbus
        register so a reviewer sees the real address behind the simulated value."""
        body = client.get("/api/v1/twin/facility/killdeer/process").json()
        regs = {r.get("reg") for s in body["stages"] for r in s["readings"] if r.get("reg")}
        assert {"40001", "40003", "40005", "40017"} <= regs  # suction/discharge/flow/vibration
        # GAS-well units: sales leads with gas at a realistic magnitude (hundreds–thousands MCFD)
        assert 200.0 <= body["sales"]["gas_mcfd"] <= 5000.0
        # condensate is a modest gas-well yield (tens of bbl/day); water > 0
        assert 5.0 <= body["sales"]["condensate_bcpd"] <= 200.0
        assert body["sales"]["water_bwpd"] > 0
        # no oil-well units on a gas wellsite
        assert "oil_bopd" not in body["sales"]

    def test_process_unknown_facility_404(self, client):
        assert client.get("/api/v1/twin/facility/nope/process").status_code == 404
