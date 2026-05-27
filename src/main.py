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

from contextlib import asynccontextmanager  # noqa: E402

import structlog  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

# API routers — these are the only ones verified to exist (CI: tests/test_imports.py)
from src.api.access_requests import router as access_requests_router  # noqa: E402
from src.api.ai import router as ai_router  # noqa: E402
from src.api.alerts import router as alerts_router  # noqa: E402
from src.api.assets import router as assets_router  # noqa: E402
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
from src.api.ping_diag import router as ping_diag_router  # noqa: E402
from src.api.predictions import router as predictions_router  # noqa: E402
from src.api.reports import router as reports_router  # noqa: E402
from src.api.weather import router as weather_router  # noqa: E402
from src.api.ws import router as ws_router  # noqa: E402
from src.collectors.simulator import SimulatorCollector  # noqa: E402
from src.collectors.snmp_router import SNMPNetworkCollector  # noqa: E402
from src.config import settings  # noqa: E402
from src.engine.alert_engine import AlertEngine  # noqa: E402
from src.engine.notifier import NotificationEngine  # noqa: E402
from src.integrations.mqtt_publisher import MQTTPublisher  # noqa: E402
from src.scheduler import PollScheduler  # noqa: E402
from src.storage.influx import InfluxStorage  # noqa: E402
from src.storage.sqlite_db import SQLiteDB  # noqa: E402

logger = structlog.get_logger()


# Asset registry — drives simulator + real-collector wiring.
LAB_ASSETS = [
    {"id": "RTR-01", "type": "router", "name": "MikroTik L009"},
    {"id": "SW-01", "type": "switch", "name": "Cisco Catalyst 2960"},
    {"id": "EDGE-01", "type": "edge", "name": "Aevus Edge (Pi)"},
    {"id": "RAD-01", "type": "radio", "name": "Trio JR900 #1"},
    {"id": "RAD-02", "type": "radio", "name": "Trio JR900 #2"},
    {"id": "RTU-01", "type": "rtu", "name": "SCADAPack 470"},
    {"id": "EFM-01", "type": "efm", "name": "ABB EFM"},
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


app_state = AppState()


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
    """
    real_targets = [
        ("RTR-01", "router", settings.mikrotik_ip, settings.poll_interval_router),
        ("SW-01", "switch", settings.catalyst_ip, settings.poll_interval_switch),
    ]
    for asset_id, device_type, host, interval in real_targets:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _register_simulators()
    _register_real_snmp_collectors()
    _register_mqtt_publisher()
    await app_state.scheduler.start()
    logger.info("aevus_main_started")
    yield
    await app_state.scheduler.stop()


app = FastAPI(
    title="Aevus Testbed",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    ping_diag_router,
    predictions_router,
    reports_router,
    weather_router,
    ws_router,
):
    app.include_router(r, prefix="/api/v1")


@app.get("/")
async def root():
    return {"service": "aevus-testbed", "version": "0.1.0", "status": "ok"}
