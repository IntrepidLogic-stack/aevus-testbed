"""
Aevus Testbed — FastAPI Application Entry Point.

Wires collectors, engines, storage, API routes, and the poll scheduler.
Imports here are the source of truth; tests/test_imports.py exercises this
module so a broken import surfaces in CI, not on the Pi during a restart.

Run with:
    uvicorn src.main:app --host 0.0.0.0 --port 8000

Configuration:
    .env file or env vars. Real SNMP collectors register automatically when
    settings.mikrotik_ip / settings.catalyst_ip resolve; simulators back-fill
    the rest of the asset registry. MQTT publishing to AWS IoT Core is
    enabled by setting mqtt_enabled=true + TLS cert paths in .env.
"""

from __future__ import annotations

# Load AWS secrets BEFORE config reads env vars
from src.secrets_loader import inject_secrets  # noqa: E402

inject_secrets()

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import structlog  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.responses import Response  # noqa: E402

# API routers — these are the only ones verified to exist (CI: tests/test_imports.py)
from src.api.access_requests import router as access_requests_router  # noqa: E402
from src.api.ai import router as ai_router  # noqa: E402
from src.api.alerts import router as alerts_router  # noqa: E402
from src.api.assets import router as assets_router  # noqa: E402
from src.api.auth import APIKeyMiddleware  # noqa: E402
from src.api.commands import router as commands_router  # noqa: E402
from src.api.correlations import router as correlations_router  # noqa: E402
from src.api.csv_io import router as csv_io_router  # noqa: E402
from src.api.deploy import router as deploy_router  # noqa: E402
from src.api.diagnostics import router as diagnostics_router  # noqa: E402
from src.api.health import router as health_router  # noqa: E402
from src.api.ingest import router as ingest_router  # noqa: E402
from src.api.integrations import router as integrations_router  # noqa: E402
from src.api.notes import journal_router  # noqa: E402
from src.api.notes import router as notes_router  # noqa: E402
from src.api.pearls import router as pearls_router  # noqa: E402
from src.api.ping_diag import router as ping_diag_router  # noqa: E402
from src.api.predictions import router as predictions_router  # noqa: E402
from src.api.reports import router as reports_router  # noqa: E402
from src.api.twin import router as twin_router  # noqa: E402
from src.api.weather import router as weather_router  # noqa: E402
from src.api.ws import router as ws_router  # noqa: E402
from src.api.ws import ws_manager  # noqa: E402 — module-level singleton
from src.collectors.pi_self_metrics import PiSelfMetricsCollector  # noqa: E402
from src.collectors.simulator import SimulatorCollector  # noqa: E402
from src.collectors.snmp_radio import TrioJR900Collector  # noqa: E402
from src.collectors.snmp_router import SNMPNetworkCollector  # noqa: E402
from src.collectors.snmp_trap_receiver import SNMPTrapReceiver  # noqa: E402
from src.config import settings  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.engine.commander import Commander  # noqa: E402
from src.engine.correlator import CorrelationEngine  # noqa: E402
from src.engine.notifier import NotificationEngine  # noqa: E402
from src.engine.weather import WeatherEngine  # noqa: E402
from src.integrations.mqtt_publisher import MQTTPublisher  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402
from src.storage.influx import InfluxStorage  # noqa: E402
from src.storage.sqlite_db import SQLiteDB  # noqa: E402

logger = structlog.get_logger()


# Asset registry — drives simulator + real-collector wiring AND first-boot
# SQLite seeding. The seed step runs on startup if the row doesn't exist, so
# /api/v1/assets is never empty (and never 500s on a fresh DB). Fields beyond
# id/type/name match the Asset pydantic model so upsert_asset() round-trips
# cleanly through SQLiteDB._row_to_asset on the next list_assets() call.
LAB_ASSETS = [
    {
        "id": "RTR-01",
        "type": "router",
        "name": "MikroTik L009",
        "vendor": "MikroTik",
        "model": "L009UiGS-2HaxD-IN",
        "location": "Lab Cabinet",
        "protocol": "snmp",
        "poll_interval": 30,
    },
    {
        "id": "SW-01",
        "type": "switch",
        "name": "Cisco Catalyst 2960",
        "vendor": "Cisco",
        "model": "Catalyst 2960",
        "location": "Lab Cabinet",
        "protocol": "snmp",
        "poll_interval": 30,
    },
    {
        "id": "EDGE-01",
        "type": "edge",
        "name": "Aevus Edge (Pi)",
        "vendor": "Raspberry Pi Foundation",
        "model": "Pi 4",
        "location": "Lab Cabinet",
        "protocol": "local",
        "poll_interval": 15,
    },
    {
        "id": "RAD-01",
        "type": "radio",
        "name": "Trio JR900 #1",
        "vendor": "Trio",
        "model": "JR900",
        "location": "Lab Cabinet",
        "protocol": "snmp",
        "poll_interval": 30,
    },
    {
        "id": "RAD-02",
        "type": "radio",
        "name": "Trio JR900 #2",
        "vendor": "Trio",
        "model": "JR900",
        "location": "Lab Cabinet",
        "protocol": "snmp",
        "poll_interval": 30,
    },
    {
        "id": "RTU-01",
        "type": "rtu",
        "name": "SCADAPack 470",
        "vendor": "Schneider Electric",
        "model": "SCADAPack 470",
        "location": "Lab Cabinet",
        "protocol": "modbus_tcp",
        "poll_interval": 5,
    },
    {
        "id": "EFM-01",
        "type": "efm",
        "name": "ABB EFM",
        "vendor": "ABB",
        "model": "TotalFlow XFCG5",
        "location": "Lab Cabinet",
        "protocol": "modbus_tcp",
        "poll_interval": 5,
    },
]


class AppState:
    """Holds shared application state accessible from route handlers."""

    def __init__(self) -> None:
        self.db = SQLiteDB()
        self.influx = InfluxStorage()
        self.alert_engine = AlertEngine()
        self.notifier = NotificationEngine()
        self.scheduler = PollScheduler(
            db=self.db,
            influx=self.influx,
            alert_engine=self.alert_engine,
            notifier=self.notifier,
        )
        self.mqtt_publisher: MQTTPublisher | None = None
        # Weather/solar engine — feeds the Solar page (GHI/DNI irradiance →
        # panel/battery model) and the /api/v1/weather endpoint. Instantiated
        # here so app_state.weather_engine always exists; lifespan starts the
        # refresh loop. Without this the weather router 500s on attribute access.
        self.weather_engine = WeatherEngine()
        # Referenced by API routers (health/correlations/commands) — must exist
        # on app_state or those endpoints 500. A single 500 among the dashboard's
        # Promise.all() refresh batch halts the whole live re-render loop, so a
        # missing attribute here silently freezes every page's live updates.
        self.correlator = CorrelationEngine()
        self.commander = Commander()
        self.ws_clients = 0
        # SNMP trap receiver — async UDP listener for unsolicited device events
        # (linkUp/linkDown, coldStart, vendor traps). Gated on snmp_trap_enabled
        # so EC2 (which doesn't need it) can opt out; Pi opts in via .env.
        # NOTE: radios send to UDP/162 (no port field in trap target); receiver
        # binds 1162 (unprivileged). Operator must add a one-time iptables NAT
        # redirect on the Pi: iptables -t nat -A PREROUTING -p udp --dport 162
        # -j REDIRECT --to-port 1162.
        self.trap_receiver: SNMPTrapReceiver | None = (
            SNMPTrapReceiver(
                db=self.db,
                ws_manager=ws_manager,
                port=settings.snmp_trap_port,
            )
            if settings.snmp_trap_enabled
            else None
        )


app_state = AppState()


async def _weather_loop() -> None:
    """Refresh weather/solar data at startup, then every weather_poll_interval.

    Open-Meteo is free + keyless; WeatherEngine caches to disk so a fetch
    failure degrades to the last good value instead of blanking the Solar page.
    """
    interval = max(60, settings.weather_poll_interval)
    while True:
        try:
            await app_state.weather_engine.poll()
        except Exception as e:  # noqa: BLE001 — never let the weather loop die
            logger.warning("weather_poll_failed", error=str(e))
        await asyncio.sleep(interval)


async def _warning_digest_loop() -> None:
    """Flush the notifier's WARNING digest on a timer (Task #201).

    WARNING-level alerts are buffered by the notifier and never emailed
    individually — this loop sends ONE roll-up email per interval, so a
    flapping vital can't flood the inbox. CRITICAL alerts still go out
    in real time. Default interval is hourly (settings.warning_digest_interval).
    """
    interval = max(300, settings.warning_digest_interval)
    while True:
        await asyncio.sleep(interval)
        try:
            await app_state.notifier.flush_warning_digest()
        except Exception as e:  # noqa: BLE001 — never let the digest loop die
            logger.warning("warning_digest_loop_failed", error=str(e))


async def _mqtt_health_publish_loop() -> None:
    """Publish MQTTPublisher health snapshot every 60s to a dedicated topic.

    AWS IoT Core has a `cloudwatchMetric` rule action — pointing a rule at
    `aevus/+/health/mqtt_publisher` lets us push `consecutive_publish_failures`
    into a CloudWatch custom metric without giving the Pi any IAM creds.
    An alarm on that metric > 0 catches half-open at FIRST failure (vs the
    in-process detector's threshold of 5).

    Cleanly skips when the publisher is missing or disconnected — we don't
    want to log spam when MQTT is disabled in dev.
    """
    while True:
        try:
            pub = app_state.mqtt_publisher
            if pub is not None and pub.connected:
                # publish_state() routes through the publisher's own failure-
                # counting path, so we benefit from the half-open detector
                # we're trying to surface. Worst case the health publish fails
                # too and the alarm fires on missing-data — which is also
                # correct (Pi can't reach IoT at all).
                health = pub.health
                await pub.publish_state(
                    asset_id="EDGE-01",
                    key="mqtt_publisher_health",
                    state_value="up" if health["connected"] else "down",
                    source="internal",
                    extra={
                        "consecutive_publish_failures": health["consecutive_publish_failures"],
                        "seconds_since_last_publish": health["seconds_since_last_publish"],
                    },
                )
        except Exception as e:  # noqa: BLE001 — health pump must not die
            logger.warning("mqtt_health_publish_failed", error=str(e))
        await asyncio.sleep(60)


def _register_simulators() -> None:
    """Register simulator collectors for every lab asset (baseline)."""
    for spec in LAB_ASSETS:
        try:
            collector = SimulatorCollector(
                asset_id=spec["id"],
                device_type=spec["type"],
                poll_interval=30,
            )
            app_state.scheduler.register(spec["id"], collector)
        except Exception as e:
            logger.warning("collector_register_failed", asset_id=spec["id"], error=str(e))


def _register_real_snmp_collectors() -> None:
    """Override simulators with REAL SNMP collectors for online SNMP-reachable
    assets. Must run AFTER _register_simulators() — scheduler.register()
    replaces existing entries.

    Network gear (MikroTik, Catalyst) uses standard MIB-II via
    SNMPNetworkCollector. Trio JR900 radios use enterprise OIDs
    (1.3.6.1.4.1.5727.*) via TrioJR900Collector — different OID tree,
    different vendor encoding, different vital interpretation.
    """
    network_targets = [
        ("RTR-01", "router", settings.mikrotik_ip, settings.poll_interval_router),
        ("SW-01", "switch", settings.catalyst_ip, settings.poll_interval_switch),
    ]
    for asset_id, device_type, host, interval in network_targets:
        if not host:
            logger.info("real_snmp_skipped_no_ip", asset_id=asset_id)
            continue
        try:
            collector = SNMPNetworkCollector(
                asset_id=asset_id,
                host=host,
                community=settings.snmp_community,
                poll_interval=interval,
                device_type=device_type,
            )
            app_state.scheduler.register(asset_id, collector)
            logger.info(
                "real_snmp_collector_registered",
                asset_id=asset_id,
                host=host,
                device_type=device_type,
            )
        except Exception as e:
            logger.warning(
                "real_snmp_collector_failed_fallback_to_sim",
                asset_id=asset_id,
                error=str(e),
            )

    # EDGE-01 (this Pi) — self-metrics via local syscalls. Always-on; no IP/SNMP
    # required. Overrides the simulator entry for EDGE-01. asset_id is forced to
    # EDGE-01 (NOT the collector's PI-01 default) to avoid the Task #97 seed
    # conflict where a separate PI-01 row got created and broke the registry.
    try:
        edge_collector = PiSelfMetricsCollector(
            asset_id="EDGE-01",
            poll_interval=15,
        )
        app_state.scheduler.register("EDGE-01", edge_collector)
        logger.info("edge_self_metrics_collector_registered", asset_id="EDGE-01")
    except Exception as e:
        logger.warning(
            "edge_self_metrics_failed_fallback_to_sim",
            asset_id="EDGE-01",
            error=str(e),
        )

    # Trio JR900 radios — dormant until IPs are set in .env (rad_01_ip / rad_02_ip)
    radio_targets = [
        ("RAD-01", settings.rad_01_ip, settings.poll_interval_radio),
        ("RAD-02", settings.rad_02_ip, settings.poll_interval_radio),
    ]
    for asset_id, host, interval in radio_targets:
        if not host:
            logger.info("real_radio_skipped_no_ip", asset_id=asset_id)
            continue
        try:
            collector = TrioJR900Collector(
                asset_id=asset_id,
                host=host,
                community=settings.snmp_community,
                poll_interval=interval,
            )
            app_state.scheduler.register(asset_id, collector)
            logger.info(
                "real_radio_collector_registered",
                asset_id=asset_id,
                host=host,
            )
        except Exception as e:
            logger.warning(
                "real_radio_collector_failed_fallback_to_sim",
                asset_id=asset_id,
                error=str(e),
            )


def _register_modbus_collectors() -> None:
    """Wire the SCADAPack 470 Modbus collector if modbus_enabled=true.

    OFF by default (Task #198). This MUST run on the EDGE Pi — it polls the
    SCADAPack at settings.scadapack_ip (172.16.1.200) over Modbus TCP, which
    is on the lab LAN. EC2 (AWS) cannot route to a 172.16.x private IP, so
    on EC2 leave modbus_enabled unset and the asset stays on the simulator.

    Registration failure falls back to the simulator entry — a SCADAPack
    that's powered off or unreachable must not crash startup or the
    scheduler. The pearl strip's EFM/RTU node will show gray (no telemetry)
    until the device is actually polling, which is the honest state.
    """
    if not settings.modbus_enabled:
        logger.info("modbus_collector_disabled_in_config")
        return
    try:
        from src.collectors.modbus_rtu import SCADAPack470Collector

        collector = SCADAPack470Collector(
            asset_id="RTU-01",
            host=settings.scadapack_ip,
            port=settings.modbus_port,
            slave_id=settings.modbus_slave_id,
            poll_interval=settings.poll_interval_rtu,
        )
        app_state.scheduler.register("RTU-01", collector)
        logger.info(
            "modbus_collector_registered",
            asset_id="RTU-01",
            host=settings.scadapack_ip,
            port=settings.modbus_port,
        )
    except Exception as e:
        logger.warning(
            "modbus_collector_failed_fallback_to_sim",
            asset_id="RTU-01",
            host=settings.scadapack_ip,
            error=str(e),
        )


def _register_mqtt_publisher() -> None:
    """Wire MQTTPublisher into the scheduler if mqtt_enabled=true in config.
    Off by default — Pi enables via .env once IoT Core certs are in place."""
    if not settings.mqtt_enabled:
        logger.info("mqtt_publisher_disabled_in_config")
        return
    try:
        app_state.mqtt_publisher = MQTTPublisher()
        app_state.scheduler.register_mqtt_publisher(app_state.mqtt_publisher)
    except Exception as e:
        logger.warning("mqtt_publisher_init_failed", error=str(e))


def _seed_lab_assets() -> None:
    """Ensure every LAB_ASSETS row exists in SQLite before the scheduler runs.

    Without this, a fresh DB has no rows and /api/v1/assets returns 200 OK with
    an empty list until the first poll cycle finishes. Worse, manual INSERTs
    with the wrong column types (see Task #133 EDGE-01 incident) crashed the
    list_assets endpoint with a 500. Seeding here via upsert_asset uses the
    Asset pydantic model — schema mismatches become startup errors, not
    runtime 500s. Only inserts; never overwrites a row that's already there
    (so health/vitals captured by the scheduler aren't clobbered on restart).
    """
    from datetime import UTC, datetime

    from src.models.asset import Asset

    for spec in LAB_ASSETS:
        if app_state.db.get_asset(spec["id"]) is not None:
            continue
        try:
            asset = Asset(
                id=spec["id"],
                type=spec["type"],
                status="unknown",
                name=spec["name"],
                location=spec["location"],
                vendor=spec["vendor"],
                model=spec["model"],
                protocol=spec["protocol"],
                poll_interval=spec["poll_interval"],
                last_seen=datetime.now(UTC),
            )
            app_state.db.upsert_asset(asset)
            logger.info("lab_asset_seeded", asset_id=spec["id"], type=spec["type"])
        except Exception as e:
            logger.warning("lab_asset_seed_failed", asset_id=spec["id"], error=str(e))


def _seed_opcua_asset() -> None:
    """Seed the OPC UA asset's registry metadata when a tag-map is configured.

    Independent of OPCUA_ENABLED so the CLOUD read-API (which does NOT poll OT) can still
    render the asset from the DynamoDB vitals the edge pushes — the read-API overlays
    live vitals onto registry assets, so the asset must exist in the registry. Idempotent:
    upserts only when the row is absent (cf. the #97/#98 seed-break — never blindly
    rewrite). No-op when no tag-map is configured, so a box without OPC UA is unchanged.
    """
    if not settings.opcua_config_path:
        return
    try:
        from src.collectors.opcua_client import load_opcua_config

        cfg = load_opcua_config(settings.opcua_config_path)
        if app_state.db.get_asset(cfg.asset_id) is None:
            app_state.db.upsert_asset(cfg.to_seed_asset())
            logger.info("opcua_asset_seeded", asset_id=cfg.asset_id)
    except Exception as e:  # noqa: BLE001 — seeding must never crash startup
        logger.warning("opcua_seed_failed", error=str(e))


def _register_opcua_collector() -> None:
    """Wire the OPC UA client collector when OPCUA_ENABLED and a tag-map is set.

    OFF by default. MUST run on the EDGE Pi — it connects to an OPC UA server on the OT
    network; EC2 cannot/should not reach customer OT, so on EC2 leave OPCUA_ENABLED unset
    (the asset still renders there from DynamoDB vitals). The collector's readings publish
    over MQTT via the scheduler, flowing to the cloud read-API like any other edge asset.
    Read-only (IL-9000). Registration failure is logged and never crashes the scheduler.
    """
    if not settings.opcua_enabled:
        return
    if not settings.opcua_config_path:
        logger.warning("opcua_enabled_but_no_config_path")
        return
    try:
        from src.collectors.opcua_client import load_opcua_config

        cfg = load_opcua_config(settings.opcua_config_path)
        app_state.scheduler.register(cfg.asset_id, cfg.to_collector())
        logger.info("opcua_collector_registered", asset_id=cfg.asset_id, endpoint=cfg.endpoint)
    except Exception as e:  # noqa: BLE001 — must not crash startup
        logger.warning("opcua_collector_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_lab_assets()
    _seed_opcua_asset()
    _register_simulators()
    _register_real_snmp_collectors()
    _register_modbus_collectors()
    _register_opcua_collector()
    _register_mqtt_publisher()
    await app_state.scheduler.start()
    weather_task = asyncio.create_task(_weather_loop())
    mqtt_health_task = asyncio.create_task(_mqtt_health_publish_loop())
    warning_digest_task = asyncio.create_task(_warning_digest_loop())
    # Start the SNMP trap listener if enabled. Failures (e.g. port-in-use on a
    # second instance, or no privileged-port capability) are logged but do NOT
    # crash startup — the rest of the service is still useful without traps.
    if app_state.trap_receiver is not None:
        try:
            await app_state.trap_receiver.start()
        except Exception as e:  # noqa: BLE001
            logger.warning("snmp_trap_receiver_start_failed", error=str(e))
    # OPC UA: the edge-bridge path (seed + scheduler collector above) supersedes the
    # P4 in-process overlay poller — the collector publishes over MQTT to the cloud, so
    # no separate poller is started here. The opcua_assets overlay stays available (and
    # self-dedupes against the registry) for standalone/direct use.
    logger.info("aevus_main_started")
    yield
    if app_state.trap_receiver is not None:
        try:
            await app_state.trap_receiver.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning("snmp_trap_receiver_stop_failed", error=str(e))
    weather_task.cancel()
    mqtt_health_task.cancel()
    warning_digest_task.cancel()
    await app_state.scheduler.stop()


app = FastAPI(
    title="Aevus Testbed",
    # Observable marker (/openapi.json). Also confirms the fixed auto-deploy now
    # self-restarts on a normal push (0.1.1 → 0.1.2 with no manual intervention).
    version="0.1.9",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Task #154: restore API-key middleware (regression — was present in initial
# commit 47e5901, accidentally dropped in a refactor between then and
# 317870f). When API_KEY is empty (dev mode) the middleware no-ops; in prod
# it enforces X-API-Key header, aevus_session cookie, or Cognito Bearer.
# Auth-test failures (5 of the 9 pre-existing failures from PR #56) caught
# this regression. See docs/TASK_BACKLOG_AUDIT_2026-05-30.md §Cluster 8.
app.add_middleware(APIKeyMiddleware)

# Register all routers under /api/v1
for r in (
    access_requests_router,
    ai_router,
    alerts_router,
    assets_router,
    commands_router,
    correlations_router,
    csv_io_router,
    deploy_router,
    diagnostics_router,
    health_router,
    ingest_router,
    integrations_router,
    journal_router,
    notes_router,
    pearls_router,
    ping_diag_router,
    predictions_router,
    reports_router,
    twin_router,
    weather_router,
    ws_router,
):
    app.include_router(r, prefix="/api/v1")


# Serve dashboard static files. The registry-backed API lives under /api/v1;
# everything below serves the single-file console + its sidecar JS assets.
# NOTE: this block was lost once when EC2's src/ was aligned to a main.py that
# only had a JSON root — keep it here so a `git checkout main -- src/` can never
# silently take the dashboard offline again.
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
STAGING_DIR = DASHBOARD_DIR.parent / "dashboard-staging"

if STAGING_DIR.exists():
    app.mount("/staging", StaticFiles(directory=str(STAGING_DIR), html=True), name="staging")

if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")


def _read_cached(path: Path) -> str | None:
    """Read a static page ONCE at import and serve it from memory thereafter.

    The root/login handlers previously `.read_text()` the ~8k-line console on
    every request — a synchronous disk read on the hot path. The deploy always
    restarts the process (deploy/deploy.sh), so a cache read at import can never
    go stale relative to the deployed file. Returns None if the file is absent
    (preserves the prior `.exists()` JSON fallback).
    """
    try:
        return path.read_text()
    except OSError:
        return None


_INDEX_HTML = _read_cached(DASHBOARD_DIR / "Aevus_Console.html")
_LOGIN_HTML = _read_cached(DASHBOARD_DIR / "login.html")


@app.get("/login")
async def login_page():
    """Serve the login page (cached at import)."""
    if _LOGIN_HTML is not None:
        return Response(content=_LOGIN_HTML, media_type="text/html")
    return {"detail": "Login page not found"}


@app.get("/")
async def root():
    """Serve the Aevus Console dashboard (cached); fall back to a JSON health blob."""
    if _INDEX_HTML is not None:
        return Response(content=_INDEX_HTML, media_type="text/html")
    return {"service": "aevus-testbed", "version": "0.1.0", "status": "ok"}
