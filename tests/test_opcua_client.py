"""Tests for the OPC UA client collector + YAML tag-map (P1/P2).

All network I/O is faked by patching ``asyncua.Client`` — these run offline and in
CI with no server. A separate (skippable) integration test can later exercise a
real opc-plc container; this file is the deterministic unit layer.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.collectors.opcua_client import (
    OPCUAClientCollector,
    OPCUAClientConfig,
    OPCUANodeSpec,
    _coerce_float,
    load_opcua_config,
)
from src.engine.normalizer import normalize_batch


def _make_fake_client_cls(values: dict, state: dict):
    """Build a fake asyncua.Client class backed by ``values`` and ``state`` dicts.

    ``state`` flags: fail_connect, fail_read. Counters: instances, connects.
    """

    class _FakeNode:
        def __init__(self, nid: str) -> None:
            self.nid = nid

        async def read_value(self):
            if state.get("fail_read"):
                raise OSError("read fail")
            return values.get(self.nid, 0.0)

    class _FakeClient:
        def __init__(self, url=None, timeout=None) -> None:
            self.url = url
            self.session_timeout = None
            state["instances"] = state.get("instances", 0) + 1

        async def connect(self):
            if state.get("fail_connect"):
                raise OSError("connect fail")
            state["connects"] = state.get("connects", 0) + 1

        async def disconnect(self):
            state["disconnects"] = state.get("disconnects", 0) + 1

        def get_node(self, nid):
            return _FakeNode(nid)

        async def read_values(self, nodes):
            if state.get("fail_read"):
                raise OSError("read fail")
            return [values.get(n.nid, 0.0) for n in nodes]

        def set_user(self, user):  # pragma: no cover - exercised only with creds
            pass

        def set_password(self, password):  # pragma: no cover
            pass

        async def set_security_string(self, s):  # pragma: no cover
            pass

    return _FakeClient


def _specs() -> list[OPCUANodeSpec]:
    return [
        OPCUANodeSpec("ns=2;s=Vib", "vibration", "mm/s", "compressor"),
        OPCUANodeSpec("ns=2;s=Suct", "suction_pressure", "PSI", "compressor"),
        OPCUANodeSpec("ns=2;s=Hours", "run_hours", "hours", "compressor"),
    ]


# ── _coerce_float ───────────────────────────────────────────────────────────
def test_coerce_float_handles_types():
    assert _coerce_float(True) == 1.0
    assert _coerce_float(False) == 0.0
    assert _coerce_float(3) == 3.0
    assert _coerce_float(2.5) == 2.5
    assert _coerce_float("4.5") == 4.5
    assert _coerce_float(None) is None
    assert _coerce_float("OPEN") is None  # non-numeric string -> skipped, not raised


# ── poll() ──────────────────────────────────────────────────────────────────
async def test_poll_maps_nodes_to_readings_and_skips_nonnumeric():
    values = {"ns=2;s=Vib": 3.1, "ns=2;s=Suct": 250.0, "ns=2;s=Hours": "n/a"}
    state: dict = {}
    col = OPCUAClientCollector("OPCUA-1", "opc.tcp://h:4840", _specs())
    with patch("asyncua.Client", _make_fake_client_cls(values, state)):
        readings = await col.poll()
    # "Hours" is non-numeric -> dropped; the two numeric nodes survive
    assert {r.metric for r in readings} == {"vibration", "suction_pressure"}
    assert all(r.source == "opcua" for r in readings)
    vib = next(r for r in readings if r.metric == "vibration")
    assert vib.value == 3.1
    assert vib.opcua_node == "ns=2;s=Vib"  # NodeId carried through
    assert vib.group == "compressor"


async def test_poll_feeds_normalizer_status_tagging():
    # a high vibration must come out 'bad'; run_hours is info -> blank status
    values = {"ns=2;s=Vib": 9.0, "ns=2;s=Suct": 250.0, "ns=2;s=Hours": 1234.0}
    state: dict = {}
    col = OPCUAClientCollector("OPCUA-1", "opc.tcp://h:4840", _specs())
    with patch("asyncua.Client", _make_fake_client_cls(values, state)):
        raw = await col.poll()
    vitals = {v.label: v for v in normalize_batch(raw)}
    assert vitals["VIBRATION"].status == "bad"  # 9.0 > crit threshold
    assert vitals["RUN HOURS"].status == ""  # info metric


async def test_is_reachable_true_then_false():
    state: dict = {}
    col = OPCUAClientCollector("OPCUA-1", "opc.tcp://h:4840", _specs())
    with patch("asyncua.Client", _make_fake_client_cls({}, state)):
        assert await col.is_reachable() is True
        state["fail_read"] = True
        assert await col.is_reachable() is False


async def test_poll_disconnects_and_reconnects_after_failure():
    values = {"ns=2;s=Vib": 1.0, "ns=2;s=Suct": 1.0, "ns=2;s=Hours": 1.0}
    state: dict = {"fail_read": True}
    col = OPCUAClientCollector("OPCUA-1", "opc.tcp://h:4840", _specs())
    with patch("asyncua.Client", _make_fake_client_cls(values, state)):
        # first poll: read raises -> poll() raises, connection torn down, backoff armed
        with pytest.raises(OSError):
            await col.poll()
        assert col._connected is False
        assert col._next_attempt > 0  # backoff scheduled
        # recover: server healthy again, clear the backoff gate, poll succeeds
        state["fail_read"] = False
        col._next_attempt = 0.0
        readings = await col.poll()
        assert len(readings) == 3
        assert state["connects"] >= 2  # a fresh session was established


# ── tag-map loader ──────────────────────────────────────────────────────────
_GOOD_YAML = """
asset:
  id: KILLDEER-OPCUA
  name: "Killdeer via SCADA"
  endpoint: opc.tcp://scada:4840
  poll_interval: 7
tags:
  - node: "ns=2;s=Suct"
    metric: suction_pressure
    unit: PSI
    group: compressor
  - node: "ns=2;s=Vib"
    metric: vibration
    unit: mm/s
    group: compressor
"""


def test_load_opcua_config_parses_and_builds_collector(tmp_path):
    p = tmp_path / "tagmap.yaml"
    p.write_text(_GOOD_YAML)
    cfg = load_opcua_config(p)
    assert isinstance(cfg, OPCUAClientConfig)
    assert cfg.asset_id == "KILLDEER-OPCUA"
    assert cfg.endpoint == "opc.tcp://scada:4840"
    assert cfg.poll_interval == 7
    assert [n.metric for n in cfg.nodes] == ["suction_pressure", "vibration"]
    col = cfg.to_collector()
    assert isinstance(col, OPCUAClientCollector)
    assert col.asset_id == "KILLDEER-OPCUA"
    assert col.poll_interval == 7
    assert len(col.nodes) == 2


@pytest.mark.parametrize(
    "body",
    [
        "asset: {}\ntags: []\n",  # no id/endpoint
        "asset:\n  id: X\n  endpoint: opc.tcp://h\ntags: []\n",  # no tags
        "asset:\n  id: X\n  endpoint: opc.tcp://h\ntags:\n  - {metric: x}\n",  # tag missing node
        "[]\n",  # not a mapping
    ],
)
def test_load_opcua_config_rejects_malformed(tmp_path, body):
    p = tmp_path / "bad.yaml"
    p.write_text(body)
    with pytest.raises(ValueError):
        load_opcua_config(p)


def test_shipped_reference_config_is_valid():
    """The committed Prosys reference tag-map must always parse."""
    from pathlib import Path

    ref = Path(__file__).resolve().parents[1] / "config" / "opcua" / "prosys_reference.yaml"
    cfg = load_opcua_config(ref)
    assert cfg.asset_id == "OPCUA-PROSYS-REF"
    assert len(cfg.nodes) == 5
