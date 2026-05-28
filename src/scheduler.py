"""
Aevus Testbed --- Polling Scheduler
Runs collectors on configured intervals and feeds the processing pipeline.

Pipeline per poll cycle:
  1. Collector.safe_poll() -> list[RawTelemetry]
  2. InfluxDB write (time-series storage)
  3. Normalizer -> list[VitalSign]
  4. Health score computation
  5. Alert engine evaluation + notification
  6. Comm quality tracking
  7. SQLite asset update
  8. WebSocket broadcast to dashboard clients
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.api.ws import ws_manager
from src.collectors.simulator import SimulatorCollector
from src.config import settings
from src.engine.firmware_tracker import FirmwareTracker
from src.engine.health_score import compute_health, health_status
from src.engine.maintenance_tracker import MaintenanceTracker
from src.engine.normalizer import normalize_batch
from src.engine.prediction import PredictionEngine

if TYPE_CHECKING:
    from src.collectors.base import BaseCollector
    from src.engine.alert_engine import AlertEngine
    from src.engine.comm_quality import CommQualityEngine
    from src.engine.correlator import CorrelationEngine
    from src.engine.notifier import NotificationEngine
    from src.engine.weather import WeatherEngine
    from src.integrations.mqtt_publisher import MQTTPublisher
    from src.storage.influx import InfluxStorage
    from src.storage.sqlite_db import SQLiteDB

logger = structlog.get_logger()

# Fallback device type mapping for simulator when real collectors fail
ASSET_DEVICE_TYPE_MAP = {
    "RTR-01": "router",
    "SW-01": "switch",
    "EDGE-01": "edge",
    "RAD-01": "radio",
    "RAD-02": "radio",
    "RTU-01": "rtu",
    "EFM-01": "efm",
}


class PollScheduler:
    """Manages polling loops for all registered collectors."""

    def __init__(
        self,
        db: SQLiteDB,
        influx: InfluxStorage,
        alert_engine: AlertEngine,
        notifier: NotificationEngine | None = None,
        weather_engine: WeatherEngine | None = None,
        comm_quality_engine: CommQualityEngine | None = None,
        correlator: CorrelationEngine | None = None,
    ) -> None:
        self.db = db
        self.influx = influx
        self.alert_engine = alert_engine
        self.notifier = notifier
        self.weather_engine = weather_engine
        self.comm_quality_engine = comm_quality_engine
        self.correlator = correlator
        self.prediction_engine = PredictionEngine(influx)
        # ISA-18.2 alarm hygiene — out-of-band firmware change + maintenance-due
        # detection. Baselines persist via SQLite so they survive service restarts.
        self.firmware_tracker = FirmwareTracker(db=db)
        self.maintenance_tracker = MaintenanceTracker(db=db)
        self._collectors: dict[str, BaseCollector] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._prediction_task: asyncio.Task | None = None
        self._weather_task: asyncio.Task | None = None
        self._mqtt_publisher: MQTTPublisher | None = None
        self.log = logger.bind(component="scheduler")

    def register_mqtt_publisher(self, publisher: MQTTPublisher) -> None:
        """Register the MQTT publisher. The scheduler will publish a copy of
        each poll-cycle's readings to the configured MQTT topic hierarchy.

        MQTT is a *bridge*, not a critical path. If it fails, local alarm
        evaluation continues unaffected — that's the entire point of
        edge-first architecture.
        """
        self._mqtt_publisher = publisher
        self.log.info("mqtt_publisher_registered", site_id=publisher.site_id)

    def register(self, asset_id: str, collector: BaseCollector) -> None:
        """Register a collector for an asset."""
        self._collectors[asset_id] = collector
        self.log.info("collector_registered", asset_id=asset_id, type=type(collector).__name__)

    async def start(self) -> None:
        """Start polling loops for all registered collectors."""
        for asset_id, collector in self._collectors.items():
            task = asyncio.create_task(self._poll_loop(asset_id, collector))
            self._tasks[asset_id] = task
            self.log.info("poll_loop_started", asset_id=asset_id, interval=collector.poll_interval)

        # Start prediction engine loop (runs every 60s)
        self._prediction_task = asyncio.create_task(self._prediction_loop())
        self.log.info("prediction_loop_started", interval=60)

        # Start weather polling loop
        if self.weather_engine:
            self._weather_task = asyncio.create_task(self._weather_loop())
            self.log.info("weather_loop_started", interval=settings.weather_poll_interval)

        # Start MQTT publisher last so any earlier-emitted events don't fail
        # with a not-yet-connected client. Failure is logged + non-fatal.
        if self._mqtt_publisher is not None:
            try:
                await self._mqtt_publisher.start()
                self.log.info("mqtt_publisher_started")
            except Exception as e:
                self.log.warning("mqtt_publisher_start_failed", error=str(e))

    async def stop(self) -> None:
        """Cancel all polling loops."""
        if self._prediction_task:
            self._prediction_task.cancel()
            self.log.info("prediction_loop_stopped")
        if self._weather_task:
            self._weather_task.cancel()
            self.log.info("weather_loop_stopped")
        if self._mqtt_publisher is not None:
            try:
                await self._mqtt_publisher.stop()
                self.log.info("mqtt_publisher_stopped")
            except Exception as e:
                self.log.warning("mqtt_publisher_stop_failed", error=str(e))
        for asset_id, task in self._tasks.items():
            task.cancel()
            self.log.info("poll_loop_stopped", asset_id=asset_id)
        self._tasks.clear()

    async def _poll_loop(self, asset_id: str, collector: BaseCollector) -> None:
        """Continuous polling loop for a single collector."""
        while True:
            try:
                await self._poll_cycle(asset_id, collector)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("poll_cycle_error", asset_id=asset_id, error=str(e))

            await asyncio.sleep(collector.poll_interval)

    async def _poll_cycle(self, asset_id: str, collector: BaseCollector) -> None:
        """Execute one poll cycle: collect -> store -> normalize -> score -> alert -> push."""
        # 1. Collect (safe_poll now tracks poll_count, success_count, duration)
        readings = await collector.safe_poll()
        # Record real-device reachability BEFORE any simulator fallback, so the
        # rolling 24h uptime % reflects whether Aevus could actually reach the
        # device — not whether the fallback produced data. Skip pure-simulator
        # collectors (no real device behind them).
        if not isinstance(collector, SimulatorCollector):
            with contextlib.suppress(Exception):
                self.db.record_reachability(asset_id, bool(readings))
        if not readings and not isinstance(collector, SimulatorCollector):
            # Real collector failed — fall back to simulator
            device_type = ASSET_DEVICE_TYPE_MAP.get(asset_id, "radio")
            fallback = SimulatorCollector(asset_id, device_type=device_type, poll_interval=collector.poll_interval)
            readings = await fallback.safe_poll()
        if not readings:
            return

        now = datetime.now(UTC)

        # 2. Write to InfluxDB
        self.influx.write_readings(readings)

        # 3. Normalize
        vitals = normalize_batch(readings)

        # 4. Extract run_hours if present (handed to MaintenanceTracker below)
        run_hours_value: int | None = None
        for r in readings:
            if r.metric == "run_hours":
                with contextlib.suppress(ValueError, TypeError):
                    run_hours_value = int(r.value)
                break

        # 5. Health score (with prediction risk if available)
        asset = self.db.get_asset(asset_id)
        prediction = self.prediction_engine.get_prediction(asset_id)
        risk_score = prediction.risk_score if prediction else None
        score = compute_health(
            vitals=vitals,
            last_seen=now,
            poll_interval=collector.poll_interval,
            risk_score=risk_score,
        )
        status = health_status(score)

        # 6. Alert evaluation
        asset_name = asset.name if asset else asset_id
        alert_changes = self.alert_engine.evaluate(asset_id, asset_name, vitals)

        # 6a. ISA-18.2 event-style alarms — firmware change + maintenance due
        if collector.firmware_version:
            fw_event = self.firmware_tracker.check(
                asset_id, asset_name, collector.firmware_version
            )
            if fw_event is not None:
                evt_alert = self.alert_engine.record_event(
                    asset_id=asset_id,
                    asset_name=asset_name,
                    event_type="FIRMWARE_CHANGED",
                    message=fw_event.to_message(),
                    severity="info",  # P4 per AEVUS_ALARM_CATALOG_v1.md A-P4-02
                )
                if evt_alert is not None:
                    alert_changes.append(evt_alert)

        if run_hours_value is not None:
            maint_event = self.maintenance_tracker.check(
                asset_id, asset_name, run_hours_value
            )
            if maint_event is not None:
                evt_alert = self.alert_engine.record_event(
                    asset_id=asset_id,
                    asset_name=asset_name,
                    event_type="MAINTENANCE_DUE",
                    message=maint_event.to_message(),
                    severity="warning",  # P3 per AEVUS_ALARM_CATALOG_v1.md A-P3-11
                )
                if evt_alert is not None:
                    alert_changes.append(evt_alert)

        # Persist alert changes
        for alert in alert_changes:
            self.db.save_alert(alert)

        # 6b. Send notifications for new alerts
        if self.notifier and alert_changes:
            for alert in alert_changes:
                if alert.status == "open":
                    try:
                        await self.notifier.notify(alert)
                    except Exception as e:
                        self.log.error("notification_error", error=str(e))

        # 7. Comm quality tracking
        if self.comm_quality_engine:
            self.comm_quality_engine.calculate(
                asset_id=asset_id,
                poll_count=collector.poll_count,
                poll_success_count=collector.poll_success_count,
                last_poll_duration_ms=collector.last_poll_duration_ms,
            )

        # 7b. Rolling 24h uptime — append as a vital so the dashboard can show
        # a real number instead of "—". None until we have samples (don't fake
        # 100%). Computed for real-device collectors only (simulators skipped
        # in step 1, so they have no reachability samples → None → no vital).
        uptime = None
        with contextlib.suppress(Exception):
            uptime = self.db.uptime_pct(asset_id)
        if uptime is not None:
            from src.models.telemetry import VitalSign
            up_status = "good" if uptime >= 99.0 else "warn" if uptime >= 95.0 else "bad"
            vitals.append(VitalSign(
                label="UPTIME 24H",
                value=f"{uptime:.1f} %",
                raw_value=uptime,
                unit="%",
                status=up_status,
                group="comms",
                source="computed",
            ))

        # 8. Update asset in SQLite
        if asset:
            asset.vitals = vitals
            asset.health = score
            asset.status = status
            asset.last_seen = now
            # Persist firmware so /api/v1/assets (and the dashboard) show the
            # real version instead of null. Collectors that read it set
            # collector.firmware_version (Trio MIB 10.1.5.0, router sysDescr).
            if collector.firmware_version:
                asset.firmware = collector.firmware_version
            self.db.upsert_asset(asset)

        # 9. WebSocket broadcast (local dashboard) + MQTT publish (cloud bridge)
        await ws_manager.broadcast(
            "asset_update",
            {
                "asset_id": asset_id,
                "health": score,
                "status": status,
                "vitals": [v.model_dump() for v in vitals],
                "timestamp": now.isoformat(),
            },
        )

        # MQTT publish — bridge to AWS IoT Core. One topic per reading so the
        # IoT Rule → SiteWise mapping can pivot directly onto asset properties.
        # Failures are logged + non-fatal — local alarming is unaffected.
        if self._mqtt_publisher is not None:
            for reading in readings:
                try:
                    await self._mqtt_publisher.publish_telemetry(
                        asset_id=reading.asset_id,
                        metric=reading.metric,
                        value=reading.value,
                        unit=reading.unit,
                        source=reading.source,
                    )
                except Exception as e:
                    self.log.warning("mqtt_telemetry_publish_failed", error=str(e))

        if alert_changes:
            await ws_manager.broadcast(
                "alert_update",
                {
                    "alerts": [a.model_dump(mode="json") for a in alert_changes],
                },
            )
            if self._mqtt_publisher is not None:
                for alert in alert_changes:
                    try:
                        await self._mqtt_publisher.publish_alert(
                            asset_id=alert.asset_id,
                            severity=alert.severity,
                            payload=alert.model_dump(mode="json"),
                        )
                    except Exception as e:
                        self.log.warning("mqtt_alert_publish_failed", error=str(e))

    async def _prediction_loop(self) -> None:
        """Run prediction analysis and cross-domain correlation every 60 seconds."""
        # Wait for initial data to accumulate
        await asyncio.sleep(30)

        while True:
            try:
                assets = self.db.list_assets()

                # Get current weather for battery-solar analysis
                weather_data = None
                if self.weather_engine:
                    weather_data = self.weather_engine.current

                for asset in assets:
                    await self.prediction_engine.analyze_asset(
                        asset_id=asset.id,
                        asset_name=asset.name,
                        asset_type=asset.type,
                        location=asset.location,
                        weather=weather_data,
                    )

                # Broadcast predictions to dashboard
                preds = self.prediction_engine.predictions
                if preds:
                    await ws_manager.broadcast(
                        "predictions_update",
                        {
                            "predictions": [p.model_dump() for p in preds],
                        },
                    )

                # Run cross-domain correlation
                if self.correlator and self.comm_quality_engine:
                    comm_scores = self.comm_quality_engine.scores
                    correlations = await self.correlator.correlate(
                        assets=assets,
                        weather=weather_data,
                        comm_quality=comm_scores,
                    )
                    if correlations:
                        await ws_manager.broadcast(
                            "correlations_update",
                            {
                                "correlations": [c.model_dump(mode="json") for c in correlations],
                            },
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("prediction_loop_error", error=str(e))

            await asyncio.sleep(60)

    async def _weather_loop(self) -> None:
        """Poll weather data at configured interval."""
        while True:
            try:
                if self.weather_engine:
                    weather = await self.weather_engine.poll()
                    # Broadcast weather to dashboard
                    from dataclasses import asdict
                    data = asdict(weather)
                    if data.get("fetched_at"):
                        data["fetched_at"] = data["fetched_at"].isoformat()
                    await ws_manager.broadcast("weather_update", data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("weather_loop_error", error=str(e))

            await asyncio.sleep(settings.weather_poll_interval)
