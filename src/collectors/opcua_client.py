"""OPC UA client collector — read-only northbound ingestion (P1).

Connects to an existing OPC UA *server* (a customer's SCADA host: Ignition,
KEPServerEX, Geo SCADA, CygNet, FactoryTalk, or a public reference server) as a
single OPC UA client, and reads a configured set of nodes into the standard
``RawTelemetry`` stream — the same pipeline the SNMP/Modbus/DNP3 collectors feed.

This is the technical core of the Sidecar positioning: Aevus reads from the SCADA
the customer already runs, instead of touching N field devices directly.

Design notes
------------
* **Read-only. IL-9000 applies.** This collector NEVER writes to an OPC UA node.
  There is no write path here, by design.
* **Poll-based**, to fit the existing APScheduler ``safe_poll`` cadence. Each poll
  is a single batched ``read_values`` round-trip over a persistent session, so it
  is cheap. (A subscription/monitored-item mode can layer on later without
  changing this contract.)
* **Persistent session with reconnect + exponential backoff.** A dropped server
  (restart, network blip) is detected on the next poll; the collector disconnects
  cleanly, backs off, and reconnects on a later cycle. ``safe_poll`` records the
  failure and returns ``[]`` in the meantime.
* **``asyncua`` is imported lazily** inside the connect path, so importing this
  module never fails on a host that has not installed the optional dependency
  (mirrors the dormant-by-default safety posture of the reference/process overlays).
* Security defaults to ``None`` for public simulation servers; real connections
  must pass a SecurityString (cert + SignAndEncrypt) — hardened in P3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.collectors.base import BaseCollector
from src.collectors.opcua_security import OPCUASecurity, ensure_client_cert

if TYPE_CHECKING:
    from src.models.telemetry import RawTelemetry

# Server_ServerStatus_State — a node present on every compliant OPC UA server,
# used as a cheap liveness probe.
_SERVER_STATE_NODE = "i=2259"

_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 60.0


@dataclass(frozen=True)
class OPCUANodeSpec:
    """One OPC UA node to read and how to label it in the telemetry stream.

    node_id : OPC UA NodeId string, e.g. "ns=3;s=Sinusoid" or "ns=2;i=1001".
    metric  : telemetry metric key (e.g. "suction_pressure").
    unit    : engineering unit string (e.g. "PSI").
    group   : logical group (compressor, well, production, ...).
    """

    node_id: str
    metric: str
    unit: str = ""
    group: str = ""


def _coerce_float(value: object) -> float | None:
    """Best-effort numeric coercion of an OPC UA value; None if not numeric.

    Booleans map to 1.0/0.0 (discrete/alarm points). Non-numeric values (strings,
    structures, None) are skipped rather than raising, so one odd tag cannot break
    a whole poll.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)  # numeric-looking strings
    except (TypeError, ValueError):
        return None


class OPCUAClientCollector(BaseCollector):
    """Read a fixed set of OPC UA nodes from one server, as ``RawTelemetry``."""

    def __init__(
        self,
        asset_id: str,
        endpoint: str,
        nodes: list[OPCUANodeSpec],
        poll_interval: int = 10,
        *,
        security: str | OPCUASecurity | None = None,
        username: str | None = None,
        password: str | None = None,
        connect_timeout: float = 10.0,
        session_timeout_ms: int = 30000,
    ) -> None:
        host = urlparse(endpoint).hostname or endpoint
        super().__init__(asset_id, host, poll_interval)
        self.endpoint = endpoint
        self.nodes = list(nodes)
        self.security = security
        self.username = username
        self.password = password
        self.connect_timeout = connect_timeout
        self.session_timeout_ms = session_timeout_ms

        self._client = None  # asyncua.Client | None (lazy)
        self._connected = False
        self._backoff = _BACKOFF_START_S
        self._next_attempt = 0.0  # time.monotonic() gate for reconnect backoff

    # ── connection lifecycle ────────────────────────────────────────────────
    async def _ensure_connected(self) -> None:
        if self._connected and self._client is not None:
            return
        now = time.monotonic()
        if now < self._next_attempt:
            raise ConnectionError(f"opcua backoff active ({self._next_attempt - now:.1f}s) for {self.endpoint}")
        try:
            from asyncua import Client
        except ImportError as e:  # optional dependency not installed
            raise RuntimeError("asyncua is not installed (pip install asyncua)") from e

        client = Client(url=self.endpoint, timeout=self.connect_timeout)
        client.session_timeout = self.session_timeout_ms
        if isinstance(self.security, OPCUASecurity):
            # Encrypted, signed channel with a client certificate (P3). Generate a
            # compliant self-signed client cert on first use if one is missing.
            if self.security.auto_generate:
                ensure_client_cert(self.security.client_cert, self.security.client_key, self.security.application_uri)
            client.application_uri = self.security.application_uri
            await client.set_security_string(self.security.security_string())
        elif isinstance(self.security, str) and self.security:
            await client.set_security_string(self.security)
        if self.username:
            client.set_user(self.username)
        if self.password:
            client.set_password(self.password)

        await client.connect()
        self._client = client
        self._connected = True
        self._backoff = _BACKOFF_START_S
        self.log.info("opcua_connected", endpoint=self.endpoint, nodes=len(self.nodes))

    async def _disconnect_quietly(self) -> None:
        client, self._client, self._connected = self._client, None, False
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass

    def _mark_failed(self) -> None:
        self._backoff = min(self._backoff * 2, _BACKOFF_MAX_S)
        self._next_attempt = time.monotonic() + self._backoff

    # ── BaseCollector contract ──────────────────────────────────────────────
    async def poll(self) -> list[RawTelemetry]:
        """Batched read of all configured nodes → RawTelemetry list.

        Raises on connection/read failure so ``safe_poll`` records it; on the way
        out it disconnects and arms the reconnect backoff.
        """
        await self._ensure_connected()
        assert self._client is not None
        try:
            ua_nodes = [self._client.get_node(spec.node_id) for spec in self.nodes]
            values = await self._client.read_values(ua_nodes)
        except Exception:
            await self._disconnect_quietly()
            self._mark_failed()
            raise

        readings: list[RawTelemetry] = []
        for spec, value in zip(self.nodes, values, strict=False):
            num = _coerce_float(value)
            if num is None:
                self.log.debug("opcua_skip_nonnumeric", node=spec.node_id, value=repr(value))
                continue
            readings.append(
                self._make_reading(
                    metric=spec.metric,
                    value=num,
                    unit=spec.unit,
                    source="opcua",
                    opcua_node=spec.node_id,
                    group=spec.group,
                )
            )
        return readings

    async def is_reachable(self) -> bool:
        """True if the server answers a read of its ServerStatus state node."""
        try:
            await self._ensure_connected()
            assert self._client is not None
            await self._client.get_node(_SERVER_STATE_NODE).read_value()
            return True
        except Exception:
            await self._disconnect_quietly()
            self._mark_failed()
            return False

    async def aclose(self) -> None:
        """Tear down the persistent session (call on shutdown)."""
        await self._disconnect_quietly()


# ── tag-map config (P2) ─────────────────────────────────────────────────────
# A customer is onboarded by writing a YAML tag-map, not by writing code: it maps
# their OPC UA NodeIds to Aevus metric keys. When a metric key matches one the
# normalizer already knows (suction_pressure, discharge_pressure, vibration, ...),
# status tagging (good/warn/bad vs thresholds) happens automatically downstream —
# no per-customer logic. Unknown metric keys pass through with no status.


@dataclass(frozen=True)
class OPCUAClientConfig:
    """A fully-described OPC UA source: one server + its mapped tags.

    Built from a YAML tag-map via :func:`load_opcua_config`. ``to_collector()``
    turns it into a ready-to-poll :class:`OPCUAClientCollector`.
    """

    asset_id: str
    endpoint: str
    nodes: list[OPCUANodeSpec]
    name: str = ""
    poll_interval: int = 10
    security: str | OPCUASecurity | None = None
    username: str | None = None
    password: str | None = None

    def to_collector(self) -> OPCUAClientCollector:
        return OPCUAClientCollector(
            self.asset_id,
            self.endpoint,
            self.nodes,
            poll_interval=self.poll_interval,
            security=self.security,
            username=self.username,
            password=self.password,
        )

    def to_seed_asset(self):
        """Registry metadata for this OPC UA source (vitals arrive via the edge feed).

        Returned so EC2 can seed the asset's metadata — the read-API overlays live
        DynamoDB vitals onto registry assets, so the asset must exist in the registry
        to render. Vitals themselves are NOT set here; they flow from the edge.
        """
        from src.models.asset import Asset

        return Asset(
            id=self.asset_id,
            type="sensor",
            name=self.name or self.asset_id,
            location="OPC UA server (Sidecar — read-only)",
            vendor="(OPC UA)",
            model="OPC UA client (northbound)",
            protocol="opcua",
            poll_interval=self.poll_interval,
        )


def load_opcua_config(path: str | Path) -> OPCUAClientConfig:
    """Parse a YAML tag-map into an :class:`OPCUAClientConfig`.

    Expected shape::

        asset:
          id: KILLDEER-OPCUA
          name: "Killdeer / BlueJay #1 — via SCADA OPC UA"
          endpoint: opc.tcp://scada-host:4840
          poll_interval: 10
          security: null            # P3: "Basic256Sha256,SignAndEncrypt,cert,key"
        tags:
          - node:  "ns=2;s=Compressor.Suction.PSI"
            metric: suction_pressure
            unit:   PSI
            group:  compressor

    Raises ``ValueError`` on a malformed/empty config so a bad file fails loudly
    at load time rather than producing a silently-empty collector.
    """
    import yaml

    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"opcua tag-map {p} is not a mapping")

    asset = raw.get("asset") or {}
    if not asset.get("id") or not asset.get("endpoint"):
        raise ValueError(f"opcua tag-map {p} requires asset.id and asset.endpoint")

    tags = raw.get("tags") or []
    nodes: list[OPCUANodeSpec] = []
    for i, t in enumerate(tags):
        if not isinstance(t, dict) or not t.get("node") or not t.get("metric"):
            raise ValueError(f"opcua tag-map {p} tag #{i} requires 'node' and 'metric'")
        nodes.append(
            OPCUANodeSpec(
                node_id=str(t["node"]),
                metric=str(t["metric"]),
                unit=str(t.get("unit", "")),
                group=str(t.get("group", "")),
            )
        )
    if not nodes:
        raise ValueError(f"opcua tag-map {p} has no tags")

    return OPCUAClientConfig(
        asset_id=str(asset["id"]),
        endpoint=str(asset["endpoint"]),
        nodes=nodes,
        name=str(asset.get("name", "")),
        poll_interval=int(asset.get("poll_interval", 10)),
        security=_parse_security(asset.get("security")),
        username=asset.get("username"),
        password=asset.get("password"),
    )


def _parse_security(raw) -> str | OPCUASecurity | None:
    """Parse the tag-map ``security`` value.

    * ``null`` -> None (anonymous/no encryption; public sim servers ONLY).
    * a string -> passed straight to asyncua's set_security_string (advanced).
    * a mapping -> structured, encrypted :class:`OPCUASecurity` (the real path).
    """
    if raw is None or isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        from src.collectors.opcua_security import DEFAULT_APP_URI, DEFAULT_CERT, DEFAULT_KEY

        return OPCUASecurity(
            policy=str(raw.get("policy", "Basic256Sha256")),
            mode=str(raw.get("mode", "SignAndEncrypt")),
            client_cert=str(raw.get("client_cert", DEFAULT_CERT)),
            client_key=str(raw.get("client_key", DEFAULT_KEY)),
            server_cert=raw.get("server_cert"),
            application_uri=str(raw.get("application_uri", DEFAULT_APP_URI)),
            auto_generate=bool(raw.get("auto_generate", True)),
        )
    raise ValueError(f"opcua security must be null, a string, or a mapping; got {type(raw).__name__}")
