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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from src.api.ws import ws_manager
from src.collectors.simulator import SimulatorCollector
from src.config import settings
from src.engine.health_score import compute_health, health_status
from src.engine.normalizer import normalize_batch
from src.engine.prediction import PredictionEngine

if TYPE_CHECKING:
    from src.collectors.base import BaseCollector
    from src.engine.alert_engine import AlertEngine
    from src.engine.comm_quality import CommQualityEngine
    from src.engine.correlator import CorrelationEngine
    from src.engine.notifier import NotificationEngine
    from src.engine.weather import WeatherEngine
    from src.storage.influx import InfluxStorage
    from src.storage.sqlite_db import SQLiteDB

logger = structlog.get_logger()


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
        self._collectors: dict[str, BaseCollector] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._prediction_task: asyncio.Task | None = None
        self._weather_task: asyncio.Task | None = None
        self.log = logger.bind(component="scheduler")

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

    async def stop(self) -> None:
        """Cancel all polling loops."""
        if self._prediction_task:
            self._prediction_task.cancel()
            self.log.info("prediction_loop_stopped")
        if self._weather_task:
            self._weather_task.cancel()
            self.log.info("weather_loop_stopped")
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
        if not readings:
            return

        now = datetime.now(UTC)

        # 2. Write to InfluxDB
        self.influx.write_readings(readings)

        # 3. Normalize
        vitals = normalize_batch(readings)

        # 4. Extract run_hours if present
        for r in readings:
            if r.metric == "run_hours":
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

        # 5b. Override status for simulated (offline) devices
        is_simulated = isinstance(collector, SimulatorCollector)
        if is_simulated:
            status = "offline"
            score = None

        # 6. Alert evaluation
        asset_name = asset.name if asset else asset_id
        alert_changes = self.alert_engine.evaluate(asset_id, asset_name, vitals)

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

        # 8. Update asset in SQLite
        if asset:
            asset.vitals = vitals
            asset.health = score
            asset.status = status
            asset.last_seen = now
            self.db.upsert_asset(asset)

        # 9. WebSocket broadcast
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

        if alert_changes:
            await ws_manager.broadcast(
                "alert_update",
                {
                    "alerts": [a.model_dump(mode="json") for a in alert_changes],
                },
            )

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
