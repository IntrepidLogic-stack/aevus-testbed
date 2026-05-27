"""
Aevus Testbed --- FastAPI Application Entry Point
Wires collectors, engines, storage, API routes, and scheduler together.

Run with:
    uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

# Load AWS secrets before config reads env vars
from src.secrets_loader import inject_secrets
inject_secrets()

import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.config import settings
from src.storage.influx import InfluxStorage
from src.storage.sqlite_db import SQLiteDB
from src.engine.alert_engine import AlertEngine
from src.scheduler import PollScheduler
from src.api.ws import ws_manager

# Collectors
from src.collectors.simulator import SimulatorCollector
from src.collectors.snmp_trap_receiver import SNMPTrapReceiver
from src.integrations.mqtt_publisher import MQTTPublisher

# API routers
from src.api import (
    assets_router,
    alerts_router,
    health_router,
    diagnostics_router,
    metrics_router,
    predictions_router,
    ws_router,
)

logger = structlog.get_logger()


class AppState:
    """Holds shared application state accessible from route handlers."""

    def __init__(self) -> None:
        self.db = SQLiteDB()
        self.influx = InfluxStorage()
        self.alert_engine = AlertEngine()
        self.scheduler = PollScheduler(
            db=self.db,
            influx=self.influx,
            alert_engine=self.alert_engine,
        )
        self.trap_receiver = SNMPTrapReceiver(
            host="0.0.0.0",
            port=162,
            community="aevus_trap",
        )
        self.scheduler.register_trap_receiver(self.trap_receiver)

        # MQTT publisher (Phase 4) — optional, off until MQTT_ENABLED=true in .env.
        # Construction picks up broker host/port/TLS/certs from settings automatically.
        if settings.mqtt_enabled:
            self.mqtt_publisher = MQTTPublisher()
            self.scheduler.register_mqtt_publisher(self.mqtt_publisher)
        else:
            self.mqtt_publisher = None

    @property
    def ws_clients(self) -> int:
        return ws_manager.client_count


# Module-level state — imported by route handlers
app_state = AppState()


def _register_simulators() -> None:
    """Register simulator collectors for all lab assets.

    These run immediately and generate realistic fake data.
    When hardware is online, replace with real collectors.
    """
    sims = [
        ("RAD-01", "radio", settings.poll_interval_radio),
        ("RAD-02", "radio", settings.poll_interval_radio),
        ("RTU-01", "rtu", settings.poll_interval_rtu),
        ("RTR-01", "router", settings.poll_interval_router),
    ]

    for asset_id, device_type, interval in sims:
        collector = SimulatorCollector(asset_id, device_type=device_type)
        collector.poll_interval = interval
        app_state.scheduler.register(asset_id, collector)


def _register_real_snmp_collectors() -> None:
    """Replace simulator entries with REAL SNMP collectors for assets
    that are physically online and SNMP-reachable. Run AFTER
    _register_simulators() so real collectors override sim entries via
    scheduler._collectors[asset_id] = collector replacement semantics."""
    from src.collectors.snmp_router import SNMPNetworkCollector

    real_targets = [
        ("RTR-01", "router", settings.mikrotik_ip, settings.poll_interval_router),
        ("SW-01",  "switch", settings.catalyst_ip,  settings.poll_interval_switch),
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
            logger.info("real_snmp_collector_registered",
                        asset_id=asset_id, host=host, device_type=device_type)
        except Exception as e:
            logger.warning("real_snmp_collector_failed_fallback_to_sim",
                           asset_id=asset_id, error=str(e))


def _seed_assets() -> None:
    """Seed the asset registry with lab hardware definitions."""
    from src.models.asset import Asset

    fleet = [
        Asset(
            id="RAD-01", type="radio", name="Trio JR900 #1",
            location="Lab Cabinet", vendor="Trio", model="JR900",
            ip_address=settings.trio_radio_1_ip, protocol="snmp",
            poll_interval=settings.poll_interval_radio,
        ),
        Asset(
            id="RAD-02", type="radio", name="Trio JR900 #2",
            location="Lab Cabinet", vendor="Trio", model="JR900",
            ip_address=settings.trio_radio_2_ip, protocol="snmp",
            poll_interval=settings.poll_interval_radio,
        ),
        Asset(
            id="RTU-01", type="rtu", name="SCADAPack 470",
            location="Lab Cabinet", vendor="Schneider", model="SCADAPack 470",
            ip_address=settings.scadapack_ip, protocol="modbus",
            poll_interval=settings.poll_interval_rtu,
        ),
        Asset(
            id="RTR-01", type="router", name="MikroTik L009",
            location="Lab Cabinet", vendor="MikroTik", model="L009UiGS-2HaxD-IN",
            ip_address=settings.mikrotik_ip, protocol="snmp",
            poll_interval=settings.poll_interval_router,
        ),
        Asset(
            id="SW-01", type="switch", name="Catalyst 2960",
            location="Lab Cabinet", vendor="Cisco", model="Catalyst 2960",
            ip_address=settings.catalyst_ip, protocol="snmp",
            poll_interval=settings.poll_interval_switch,
        ),
    ]

    for asset in fleet:
        app_state.db.upsert_asset(asset)

    logger.info("assets_seeded", count=len(fleet))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("aevus_starting", version="0.1.0")

    # Reconnect DB if it was closed (e.g. between TestClient sessions)
    app_state.db.reconnect()

    # Seed asset registry
    _seed_assets()

    # Register collectors (simulators for now)
    _register_simulators()
    _register_real_snmp_collectors()

    # Start SNMP trap receiver (UDP 162) — wire to scheduler consumer loop
    await app_state.trap_receiver.start()
    logger.info("trap_receiver_wired", host="0.0.0.0", port=162, community="aevus_trap")

    # Start polling
    await app_state.scheduler.start()

    logger.info("aevus_ready", assets=len(app_state.db.list_assets()))

    yield

    # Shutdown
    logger.info("aevus_shutting_down")
    await app_state.scheduler.stop()
    await app_state.trap_receiver.stop()
    app_state.influx.close()
    app_state.db.close()


# ── FastAPI App ──

app = FastAPI(
    title="Aevus SCADA Intelligence API",
    description="Real-time telemetry, health scoring, and alerts for midstream oil & gas infrastructure",
    version="0.1.0",
    lifespan=lifespan,
)

# API Key Authentication
from src.api.auth import APIKeyMiddleware
app.add_middleware(APIKeyMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes under /api/v1
app.include_router(assets_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(diagnostics_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")


# Serve dashboard static files
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")


@app.get("/")
async def root():
    """Serve dashboard or API status."""
    index = DASHBOARD_DIR / "Aevus_Console.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "service": "Aevus SCADA Intelligence",
        "version": "0.1.0",
        "status": "online",
        "docs": "/docs",
    }
