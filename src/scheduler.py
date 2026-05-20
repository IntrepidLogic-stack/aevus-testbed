"""
Aevus Testbed --- Polling Scheduler
Runs collectors on configured intervals and feeds the processing pipeline.

Pipeline per poll cycle:
  1. Collector.safe_poll() -> list[RawTelemetry]
  2. InfluxDB write (time-series storage)
  3. Normalizer -> list[VitalSign]
  4. Health score computation
  5. Alert engine evaluation
  6. SQLite asset update
  7. WebSocket broadcast to dashboard clients
"""

from __future__ import annotations

import asyncio
import structlog
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from src.collectors.base import BaseCollector
from src.collectors.dnp3_unsolicited import DNP3Event, DNP3UnsolicitedReceiver
from src.collectors.icmp_probe import ICMPProbe, ReachabilityEvent
from src.collectors.snmp_trap_receiver import SNMPTrapReceiver, TrapEvent
from src.integrations.mqtt_publisher import MQTTPublisher
from src.models.telemetry import RawTelemetry
from src.config import settings
from src.engine.normalizer import normalize_batch
from src.engine.health_score import compute_health, health_status
from src.engine.alert_engine import AlertEngine
from src.engine.prediction import PredictionEngine
from src.storage.influx import InfluxStorage
from src.storage.sqlite_db import SQLiteDB
from src.api.ws import ws_manager

if TYPE_CHECKING:
    from src.models.asset import Asset

logger = structlog.get_logger()


class PollScheduler:
    """Manages polling loops for all registered collectors."""

    def __init__(
        self,
        db: SQLiteDB,
        influx: InfluxStorage,
        alert_engine: AlertEngine,
    ) -> None:
        self.db = db
        self.influx = influx
        self.alert_engine = alert_engine
        self.prediction_engine = PredictionEngine(influx)
        self._collectors: dict[str, BaseCollector] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._prediction_task: Optional[asyncio.Task] = None
        self._staleness_task: Optional[asyncio.Task] = None
        self._trap_receiver: Optional[SNMPTrapReceiver] = None
        self._trap_consumer_task: Optional[asyncio.Task] = None
        self._icmp_probe: Optional[ICMPProbe] = None
        self._icmp_consumer_task: Optional[asyncio.Task] = None
        self._dnp3_receivers: dict[str, DNP3UnsolicitedReceiver] = {}
        self._dnp3_consumer_tasks: dict[str, asyncio.Task] = {}
        self._mqtt_publisher: Optional[MQTTPublisher] = None
        self.log = logger.bind(component="scheduler")

    def register(self, asset_id: str, collector: BaseCollector) -> None:
        """Register a collector for an asset."""
        self._collectors[asset_id] = collector
        self.log.info("collector_registered", asset_id=asset_id, type=type(collector).__name__)

    def register_mqtt_publisher(self, publisher: MQTTPublisher) -> None:
        """Register the MQTT publisher. The scheduler will publish a
        copy of every WebSocket broadcast to the configured topic
        hierarchy.

        MQTT is a *bridge*, not a critical path. If it fails, local
        alarming continues unaffected — this is the entire reason we
        keep alarm evaluation at the edge.
        """
        self._mqtt_publisher = publisher
        self.log.info("mqtt_publisher_registered", site_id=publisher.site_id)

    def register_dnp3_receiver(self, receiver: DNP3UnsolicitedReceiver) -> None:
        """Register a DNP3 unsolicited-response receiver (one per RTU).

        Unlike traps and ICMP (single fleet-wide listener), DNP3 is a
        point-to-point session: one TCP connection per outstation. The
        scheduler manages a dict keyed by asset_id.
        """
        self._dnp3_receivers[receiver.asset_id] = receiver
        self.log.info(
            "dnp3_receiver_registered",
            asset_id=receiver.asset_id,
            host=receiver.host,
            outstation=receiver.outstation_address,
        )

    def register_icmp_probe(self, probe: ICMPProbe) -> None:
        """Register the ICMP probe (single instance, fleet-wide).

        Like the trap receiver, ICMP is push-driven and source-routed:
        the probe pings each registered target and emits events only on
        state transitions. The scheduler owns lifecycle and routing.
        """
        self._icmp_probe = probe
        self.log.info("icmp_probe_registered", target_count=len(probe.targets))

    def register_trap_receiver(self, receiver: SNMPTrapReceiver) -> None:
        """Register the SNMP trap receiver (single instance, fleet-wide).

        Wired separately from per-asset collectors because traps are
        push-driven and source-routed: the receiver listens on one UDP
        port for every device and dispatches by source IP to asset.
        """
        self._trap_receiver = receiver
        self.log.info("trap_receiver_registered", port=receiver.port)

    async def start(self) -> None:
        """Start polling loops for all registered collectors."""
        for asset_id, collector in self._collectors.items():
            task = asyncio.create_task(self._poll_loop(asset_id, collector))
            self._tasks[asset_id] = task
            self.log.info("poll_loop_started", asset_id=asset_id, interval=collector.poll_interval)

        # Start prediction engine loop (runs every 60s)
        self._prediction_task = asyncio.create_task(self._prediction_loop())
        self.log.info("prediction_loop_started", interval=60)

        # Start independent staleness sweep — fires comms-loss alerts even
        # if a poll task hangs or dies. Defense in depth for the primary
        # offline check inside _poll_cycle.
        self._staleness_task = asyncio.create_task(self._staleness_sweep())
        self.log.info(
            "staleness_sweep_started",
            interval=settings.staleness_sweep_interval,
            missed_polls_threshold=settings.missed_polls_offline,
        )

        # Start the SNMP trap consumer if a receiver has been registered.
        # The receiver binds UDP 162 and pushes TrapEvents onto its queue;
        # this loop drains the queue and routes events to the alert
        # engine. Without this loop the trap path is silent.
        if self._trap_receiver is not None:
            await self._trap_receiver.start()
            self._trap_consumer_task = asyncio.create_task(self._trap_consumer_loop())
            self.log.info("trap_consumer_started")

        # Start the ICMP probe + consumer if a probe has been registered.
        # The probe fires reachability events sub-second; the consumer
        # routes them through evaluate_reachability.
        if self._icmp_probe is not None:
            await self._icmp_probe.start()
            self._icmp_consumer_task = asyncio.create_task(self._icmp_consumer_loop())
            self.log.info("icmp_consumer_started")

        # Start each DNP3 receiver + its consumer loop. One TCP session
        # per outstation; we run a consumer per asset so a stuck event
        # for one RTU can't backpressure another.
        for asset_id, receiver in self._dnp3_receivers.items():
            await receiver.start()
            task = asyncio.create_task(self._dnp3_consumer_loop(asset_id))
            self._dnp3_consumer_tasks[asset_id] = task
            self.log.info("dnp3_consumer_started", asset_id=asset_id)

        # MQTT publisher — bridge to IoT Core (or local Mosquitto in dev).
        # Started after all collectors so the first events publish over
        # an already-connected session if possible. The scheduler does
        # NOT block on the publisher; if MQTT is down, alarming
        # continues local-only.
        if self._mqtt_publisher is not None:
            await self._mqtt_publisher.start()
            self.log.info("mqtt_publisher_started")

    async def stop(self) -> None:
        """Cancel all polling loops."""
        if self._prediction_task:
            self._prediction_task.cancel()
            self.log.info("prediction_loop_stopped")
        if self._staleness_task:
            self._staleness_task.cancel()
            self.log.info("staleness_sweep_stopped")
        if self._trap_consumer_task:
            self._trap_consumer_task.cancel()
            self.log.info("trap_consumer_stopped")
        if self._trap_receiver:
            await self._trap_receiver.stop()
        if self._icmp_consumer_task:
            self._icmp_consumer_task.cancel()
            self.log.info("icmp_consumer_stopped")
        if self._icmp_probe:
            await self._icmp_probe.stop()
        for asset_id, task in self._dnp3_consumer_tasks.items():
            task.cancel()
            self.log.info("dnp3_consumer_stopped", asset_id=asset_id)
        for asset_id, receiver in self._dnp3_receivers.items():
            await receiver.stop()
            self.log.info("dnp3_receiver_stopped", asset_id=asset_id)
        self._dnp3_consumer_tasks.clear()
        if self._mqtt_publisher is not None:
            await self._mqtt_publisher.stop()
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
        # 1. Collect
        readings = await collector.safe_poll()
        if not readings:
            # Device unreachable this cycle. Evaluate staleness against the
            # last-known good timestamp and emit / resolve the OFFLINE alert
            # here so a single dropped device shows up in the dashboard
            # without waiting for the independent sweep loop.
            await self._handle_offline(asset_id, collector)
            return

        now = datetime.now(timezone.utc)

        # 2. Write to InfluxDB
        self.influx.write_readings(readings)

        # 3. Normalize
        vitals = normalize_batch(readings)

        # 4. Extract run_hours if present
        run_hours = None
        for r in readings:
            if r.metric == "run_hours":
                run_hours = r.value
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

        # 6b. Partial-telemetry check — device responded but some expected
        # metrics are missing (e.g. one Modbus channel timing out while the
        # rest still read). Only meaningful when the collector declared an
        # expected_metrics set.
        expected = getattr(collector, "expected_metrics", frozenset())
        if expected:
            actual = {r.metric for r in readings}
            missing = set(expected) - actual
            partial_change = self.alert_engine.evaluate_partial(
                asset_id, asset_name, missing
            )
            if partial_change is not None:
                alert_changes.append(partial_change)

        # Persist alert changes
        for alert in alert_changes:
            self.db.save_alert(alert)

        # 7. Update asset in SQLite
        if asset:
            asset.vitals = vitals
            asset.health = score
            asset.status = status
            asset.last_seen = now
            self.db.upsert_asset(asset)

        # 8. WebSocket broadcast (local dashboard) + MQTT publish (cloud)
        await ws_manager.broadcast("asset_update", {
            "asset_id": asset_id,
            "health": score,
            "status": status,
            "vitals": [v.model_dump() for v in vitals],
            "timestamp": now.isoformat(),
        })
        # Per-reading MQTT telemetry — one topic per metric so SiteWise's
        # IoT Core rule can pivot directly onto asset properties.
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
            await ws_manager.broadcast("alert_update", {
                "alerts": [a.model_dump(mode="json") for a in alert_changes],
            })
            await self._publish_alerts(alert_changes)

    async def _prediction_loop(self) -> None:
        """Run prediction analysis on all assets every 60 seconds."""
        # Wait for initial data to accumulate
        await asyncio.sleep(30)

        while True:
            try:
                assets = self.db.list_assets()
                for asset in assets:
                    await self.prediction_engine.analyze_asset(
                        asset_id=asset.id,
                        asset_name=asset.name,
                        asset_type=asset.type,
                        location=asset.location,
                    )

                # Broadcast predictions to dashboard
                preds = self.prediction_engine.predictions
                if preds:
                    await ws_manager.broadcast("predictions_update", {
                        "predictions": [p.model_dump() for p in preds],
                    })

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("prediction_loop_error", error=str(e))

            await asyncio.sleep(60)

    async def _handle_offline(self, asset_id: str, collector: BaseCollector) -> None:
        """Evaluate the OFFLINE state for one asset and emit side-effects.

        Idempotent: safe to call from both ``_poll_cycle`` (on empty reads)
        and the independent ``_staleness_sweep``. The alert engine itself
        deduplicates open alerts, so repeated invocations are no-ops once
        the asset is already flagged.
        """
        asset = self.db.get_asset(asset_id)
        if asset is None:
            return

        alert_change = self.alert_engine.evaluate_offline(
            asset_id=asset_id,
            asset_name=asset.name,
            last_seen=asset.last_seen,
            poll_interval=collector.poll_interval,
        )

        # Reflect the offline state on the asset row regardless of whether a
        # new alert was emitted — status should track reality, not just the
        # transition.
        is_offline = any(
            a.asset_id == asset_id and a.status == "open"
            for a in self.alert_engine.open_alerts
            if a.message and "comms loss" in a.message.lower()
        )
        new_status = "offline" if is_offline else asset.status
        status_changed = new_status != asset.status

        if status_changed:
            asset.status = new_status
            self.db.upsert_asset(asset)
            await ws_manager.broadcast("asset_update", {
                "asset_id": asset_id,
                "health": asset.health,
                "status": asset.status,
                "vitals": [v.model_dump() for v in asset.vitals],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        if alert_change is not None:
            self.db.save_alert(alert_change)
            await ws_manager.broadcast("alert_update", {
                "alerts": [alert_change.model_dump(mode="json")],
            })
            await self._publish_alerts([alert_change])

    async def _publish_alerts(self, alerts: list) -> None:
        """Mirror an alert_update broadcast onto MQTT.

        WebSocket goes to the local dashboard; MQTT goes to AWS IoT
        Core (or local Mosquitto). Both feeds are fire-and-forget from
        the scheduler's perspective — no awaits on the cloud path.
        """
        if self._mqtt_publisher is None:
            return
        for alert in alerts:
            try:
                await self._mqtt_publisher.publish_alert(
                    asset_id=alert.asset_id,
                    severity=alert.severity,
                    payload=alert.model_dump(mode="json"),
                )
            except Exception as e:
                self.log.warning(
                    "mqtt_alert_publish_failed",
                    alert_id=alert.id,
                    error=str(e),
                )

    async def _trap_consumer_loop(self) -> None:
        """Drain the SNMP trap receiver queue and route events to alerts.

        Runs for the lifetime of the scheduler. Each TrapEvent is mapped
        to alert state changes via AlertEngine.evaluate_event(); changes
        are persisted to SQLite and broadcast to dashboard WebSocket
        clients. Unknown source IPs (no asset registered) are logged and
        dropped — they're either rogue devices or misconfigured trap
        targets.
        """
        assert self._trap_receiver is not None, "trap consumer started without receiver"
        receiver = self._trap_receiver

        while True:
            try:
                event: TrapEvent = await receiver.events.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("trap_consumer_recv_error", error=str(e))
                continue

            try:
                await self._handle_trap_event(event)
            except Exception as e:
                self.log.error(
                    "trap_consumer_handle_error",
                    error=str(e),
                    source_ip=event.source_ip,
                    event_type=event.event_type,
                )

    async def _handle_trap_event(self, event: TrapEvent) -> None:
        """Process a single TrapEvent end to end.

        Resolves the source IP to an asset if the receiver didn't already
        (lets us register the receiver before any assets are seeded);
        invokes the alert engine; persists and broadcasts the changes.
        """
        asset_id = event.asset_id
        if asset_id is None:
            # Late-bind asset_id from the DB. The receiver may have been
            # configured before the asset registry was populated.
            asset = self.db.get_asset_by_ip(event.source_ip)
            if asset is None:
                self.log.warning(
                    "trap_from_unknown_source",
                    source_ip=event.source_ip,
                    event_type=event.event_type,
                )
                return
            asset_id = asset.id
            asset_name = asset.name
        else:
            asset = self.db.get_asset(asset_id)
            asset_name = asset.name if asset else asset_id

        changes = self.alert_engine.evaluate_event(
            asset_id=asset_id,
            asset_name=asset_name,
            event_type=event.event_type,
            varbinds=event.varbinds,
        )

        for alert in changes:
            self.db.save_alert(alert)

        if changes:
            await ws_manager.broadcast(
                "alert_update",
                {"alerts": [a.model_dump(mode="json") for a in changes]},
            )
            await self._publish_alerts(changes)

        # Publish the raw trap on the events topic regardless of whether
        # the alert engine emitted state changes. This is the audit
        # trail SiteWise / S3 Object Lock will key off.
        if self._mqtt_publisher is not None:
            try:
                await self._mqtt_publisher.publish_event(
                    asset_id=asset_id,
                    event_class="snmp-trap",
                    payload={
                        "event_type": event.event_type,
                        "trap_oid": event.trap_oid,
                        "source_ip": event.source_ip,
                        "community": event.community,
                        "varbinds": {k: str(v) for k, v in event.varbinds.items()},
                        "received_at": event.received_at.isoformat(),
                    },
                    source="trap",
                )
            except Exception as e:
                self.log.warning("mqtt_trap_publish_failed", error=str(e))

    async def _icmp_consumer_loop(self) -> None:
        """Drain the ICMP probe queue and route reachability transitions.

        Same pattern as _trap_consumer_loop. The probe only emits on
        state transitions, so this loop's volume is low even with a
        large fleet — empty queue waits are normal.
        """
        assert self._icmp_probe is not None, "icmp consumer started without probe"
        probe = self._icmp_probe

        while True:
            try:
                event: ReachabilityEvent = await probe.events.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("icmp_consumer_recv_error", error=str(e))
                continue

            try:
                await self._handle_reachability_event(event)
            except Exception as e:
                self.log.error(
                    "icmp_consumer_handle_error",
                    error=str(e),
                    asset_id=event.asset_id,
                    state=event.state,
                )

    async def _handle_reachability_event(self, event: ReachabilityEvent) -> None:
        """Route one ReachabilityEvent through the alert engine."""
        asset = self.db.get_asset(event.asset_id)
        asset_name = asset.name if asset else event.asset_id

        changes = self.alert_engine.evaluate_reachability(
            asset_id=event.asset_id,
            asset_name=asset_name,
            state=event.state,
            loss_pct=event.loss_pct,
            avg_rtt_ms=event.avg_rtt_ms,
            consecutive_failures=event.consecutive_failures,
        )

        for alert in changes:
            self.db.save_alert(alert)

        if changes:
            await ws_manager.broadcast(
                "alert_update",
                {"alerts": [a.model_dump(mode="json") for a in changes]},
            )
            await self._publish_alerts(changes)

        # Also broadcast the raw reachability state so the dashboard can
        # render the L3 indicator independently of the alarm list.
        await ws_manager.broadcast("reachability_update", {
            "asset_id": event.asset_id,
            "host": event.host,
            "state": event.state,
            "previous_state": event.previous_state,
            "loss_pct": round(event.loss_pct, 1),
            "avg_rtt_ms": round(event.avg_rtt_ms, 2) if event.avg_rtt_ms else None,
            "timestamp": event.received_at.isoformat(),
        })
        # Mirror to MQTT under the state/reachability topic.
        if self._mqtt_publisher is not None:
            try:
                await self._mqtt_publisher.publish_state(
                    asset_id=event.asset_id,
                    key="reachability",
                    state_value=event.state,
                    source="icmp",
                    extra={
                        "previous_state": event.previous_state,
                        "loss_pct": round(event.loss_pct, 1),
                        "avg_rtt_ms": round(event.avg_rtt_ms, 2) if event.avg_rtt_ms else None,
                        "host": event.host,
                    },
                )
            except Exception as e:
                self.log.warning("mqtt_reachability_publish_failed", error=str(e))

    async def _dnp3_consumer_loop(self, asset_id: str) -> None:
        """Drain one DNP3 receiver's queue and route events through the
        existing alert engine.

        We normalize DNP3Event → RawTelemetry → VitalSign so the same
        threshold rules already governing the Modbus poller fire here
        too. One alarm logic store across both paths — no duplicate
        rule definitions, no drift.

        Critically: this loop is what makes the P-008 patent claim real.
        Latency from device-timestamp to alert_fired is logged on every
        event so we have evidence for the sub-500ms benchmark.
        """
        receiver = self._dnp3_receivers.get(asset_id)
        if receiver is None:
            self.log.error("dnp3_consumer_no_receiver", asset_id=asset_id)
            return

        while True:
            try:
                event: DNP3Event = await receiver.events.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(
                    "dnp3_consumer_recv_error", asset_id=asset_id, error=str(e)
                )
                continue

            try:
                await self._handle_dnp3_event(event)
            except Exception as e:
                self.log.error(
                    "dnp3_consumer_handle_error",
                    asset_id=asset_id,
                    metric=event.metric,
                    error=str(e),
                )

    async def _handle_dnp3_event(self, event: DNP3Event) -> None:
        """Normalize one DNP3 event and route through the alert pipeline."""
        # Latency telemetry — what proves the patent.
        latency_ms = event.latency_ms
        if latency_ms is not None:
            self.log.info(
                "dnp3_event_latency",
                asset_id=event.asset_id,
                metric=event.metric,
                latency_ms=round(latency_ms, 2),
            )

        # Coerce DNP3Event value to a float for RawTelemetry compatibility.
        # Boolean inputs become 0.0/1.0; analog inputs already float.
        if event.event_class == "binary_input":
            float_value = 1.0 if event.value else 0.0
        else:
            try:
                float_value = float(event.value)
            except (TypeError, ValueError):
                self.log.warning(
                    "dnp3_value_not_numeric",
                    metric=event.metric,
                    value=event.value,
                )
                return

        reading = RawTelemetry(
            asset_id=event.asset_id,
            metric=event.metric,
            value=float_value,
            unit=event.unit,
            timestamp=event.received_at,
            source="dnp3",
        )

        # Write the raw event to InfluxDB so the time-series record is
        # complete regardless of which path produced it (DNP3 or Modbus).
        try:
            self.influx.write_readings([reading])
        except Exception as e:
            self.log.warning("dnp3_influx_write_failed", error=str(e))

        # Normalize → VitalSigns → existing alert engine. One rule store.
        vitals = normalize_batch([reading])
        asset = self.db.get_asset(event.asset_id)
        asset_name = asset.name if asset else event.asset_id

        changes = self.alert_engine.evaluate(event.asset_id, asset_name, vitals)

        # ICMP-up logic applies here too: receiving a DNP3 event is
        # ironclad proof of life — auto-resolve any open OFFLINE /
        # UNREACHABLE alerts for this asset.
        for stale_key in ("OFFLINE", "UNREACHABLE"):
            full_key = (event.asset_id, stale_key)
            if full_key in self.alert_engine._open_alerts:
                stale = self.alert_engine._open_alerts[full_key]
                stale.status = "resolved"
                stale.resolved_at = datetime.now(timezone.utc)
                del self.alert_engine._open_alerts[full_key]
                changes.append(stale)
                self.log.info(
                    "alert_resolved_by_dnp3_event",
                    alert_id=stale.id,
                    key=stale_key,
                    asset=event.asset_id,
                )

        for alert in changes:
            self.db.save_alert(alert)

        if changes:
            await ws_manager.broadcast(
                "alert_update",
                {"alerts": [a.model_dump(mode="json") for a in changes]},
            )
            await self._publish_alerts(changes)

        # Always broadcast the raw real-time vital so the dashboard can
        # render the latched value the instant it changes — this is the
        # "AI sees the alarm before the operator" demo path.
        dnp3_payload = {
            "asset_id": event.asset_id,
            "event_class": event.event_class,
            "point_index": event.point_index,
            "metric": event.metric,
            "value": event.value,
            "unit": event.unit,
            "quality_flags": event.quality_flags,
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "device_timestamp": event.device_timestamp.isoformat() if event.device_timestamp else None,
            "received_at": event.received_at.isoformat(),
        }
        await ws_manager.broadcast("dnp3_event", dnp3_payload)

        # Mirror to MQTT under both events/dnp3 (audit trail with
        # latency metric) AND telemetry/<metric> (so SiteWise gets the
        # value alongside the polled path). The latency metric on the
        # event payload is the P-008 patent-relevant signal.
        if self._mqtt_publisher is not None:
            try:
                await self._mqtt_publisher.publish_event(
                    asset_id=event.asset_id,
                    event_class="dnp3",
                    payload=dnp3_payload,
                    source="dnp3",
                )
                await self._mqtt_publisher.publish_telemetry(
                    asset_id=event.asset_id,
                    metric=event.metric,
                    value=float_value,
                    unit=event.unit,
                    source="dnp3",
                )
            except Exception as e:
                self.log.warning("mqtt_dnp3_publish_failed", error=str(e))

    async def _staleness_sweep(self) -> None:
        """Independent comms-loss sweep.

        Runs on a fixed cadence regardless of per-asset poll intervals so a
        hung poll task can never silently suppress an OFFLINE alert. The
        per-cycle check inside ``_poll_cycle`` is the primary path; this is
        defense in depth.
        """
        interval = settings.staleness_sweep_interval
        while True:
            try:
                for asset_id, collector in self._collectors.items():
                    await self._handle_offline(asset_id, collector)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("staleness_sweep_error", error=str(e))

            await asyncio.sleep(interval)
