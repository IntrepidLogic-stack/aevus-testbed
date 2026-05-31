"""
MQTT publisher — bridges Aevus events to a broker.

Two modes, selected by config:
  • LOCAL  → Mosquitto on the Pi (no TLS, anonymous or password)
             Useful for dev work before AWS Activate is confirmed.
  • CLOUD  → AWS IoT Core endpoint with X.509 mutual TLS.
             Activated by setting the cert / key / CA paths and a
             real endpoint host in the config.

The publisher is idempotent and fire-and-forget: every event the
scheduler currently broadcasts via WebSocket is *also* published to
the corresponding MQTT topic. A failed publish logs but does not
block the scheduler — local alarming continues regardless of cloud
connectivity (this is the entire point of edge-first architecture).

Library:
  aiomqtt (the maintained successor to asyncio-mqtt). Wraps paho-mqtt
  with an asyncio-native context manager.

Outgoing payload format (JSON):
  {
    "schema_version": "1.0",
    "ts": "2026-05-20T12:00:00.123Z",
    "site_id": "lab",
    "asset_id": "RTU-01",
    "type": "telemetry" | "state" | "event" | "alert" | "heartbeat",
    "source": "modbus" | "snmp" | "dnp3" | "icmp" | "trap" | "internal",
    "payload": { ...event-specific... }
  }

Schema is intentionally simple and stable. AWS IoT Core rules + the
SiteWise IoT-Core-to-asset-property mapping key off these fields.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import settings
from src.integrations import topic_map

logger = structlog.get_logger()


# Schema version for the envelope. Bump on breaking changes; AWS rules
# can filter on this to handle migrations gracefully.
ENVELOPE_SCHEMA_VERSION = "1.0"


class MQTTPublisher:
    """Async MQTT publisher with reconnect.

    Use as an async context manager OR via start()/stop(). The publish
    methods are safe to call before connect — messages are dropped with
    a warning rather than blocking the scheduler (edge alarming MUST
    NOT depend on cloud connectivity).
    """

    def __init__(
        self,
        broker_host: str | None = None,
        broker_port: int | None = None,
        site_id: str | None = None,
        client_id: str | None = None,
        tls_enabled: bool | None = None,
        ca_cert_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
        qos: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.broker_host = broker_host or settings.mqtt_broker_host
        self.broker_port = broker_port or settings.mqtt_broker_port
        self.site_id = site_id or settings.mqtt_site_id
        self.client_id = client_id or settings.mqtt_client_id
        self.tls_enabled = tls_enabled if tls_enabled is not None else settings.mqtt_tls_enabled
        self.ca_cert_path = ca_cert_path or settings.mqtt_ca_cert_path
        self.client_cert_path = client_cert_path or settings.mqtt_client_cert_path
        self.client_key_path = client_key_path or settings.mqtt_client_key_path
        self.qos = qos if qos is not None else settings.mqtt_qos
        self.username = username or settings.mqtt_username
        self.password = password or settings.mqtt_password

        self._client: Any = None  # aiomqtt.Client — lazy-imported in connect()
        self._connected: bool = False
        self._reconnect_task: asyncio.Task | None = None
        self._stop: asyncio.Event = asyncio.Event()
        # Half-open detection (Task #151). If a publish raises or times out
        # this many times in a row, we assume the MQTT session is dead even
        # if paho's socket still looks alive, and trip the reconnect signal.
        self._reconnect_signal: asyncio.Event = asyncio.Event()
        self._consecutive_failures: int = 0
        self._last_successful_publish: datetime | None = None
        self.log = logger.bind(
            component="mqtt_publisher",
            broker=f"{self.broker_host}:{self.broker_port}",
            tls=self.tls_enabled,
            site_id=self.site_id,
        )

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the publisher's connection + reconnect supervisor."""
        if self._reconnect_task is not None:
            return
        self._stop.clear()
        self._reconnect_task = asyncio.create_task(self._supervisor_loop())
        self.log.info("mqtt_publisher_started")

    async def stop(self) -> None:
        """Stop the publisher and close the broker connection."""
        self._stop.set()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None
        await self._disconnect()
        self.log.info("mqtt_publisher_stopped")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def health(self) -> dict[str, Any]:
        """Snapshot for /api/v1/health/summary + CloudWatch metric pump.

        Lets operators see the half-open detector's counter without
        scraping logs, and gives us a probe for the next outage post-mortem.
        """
        last_pub = self._last_successful_publish
        return {
            "connected": self._connected,
            "consecutive_publish_failures": self._consecutive_failures,
            "last_successful_publish": last_pub.isoformat() if last_pub else None,
            "seconds_since_last_publish": ((datetime.now(UTC) - last_pub).total_seconds() if last_pub else None),
        }

    # ──────────────────────────────────────────────────────────────────
    # Connection management
    # ──────────────────────────────────────────────────────────────────

    async def _supervisor_loop(self) -> None:
        """Maintain a connection with backoff reconnect.

        Wakes for either (a) shutdown, (b) the _reconnect_signal raised by
        _publish() after too many consecutive failures (half-open
        detection), or (c) the aiomqtt context manager raising on
        underlying transport errors.
        """
        backoff = settings.mqtt_initial_backoff
        while not self._stop.is_set():
            try:
                await self._connect()
                # Successful connect — reset backoff so a single bad
                # network blip doesn't permanently push us to max delay.
                backoff = settings.mqtt_initial_backoff
                self._reconnect_signal.clear()
                # Wait for either shutdown or a half-open detection
                # signal from the publish path. Drop the old sleep(1)
                # busy-wait, which never re-checked link health.
                stop_task = asyncio.create_task(self._stop.wait())
                reconn_task = asyncio.create_task(self._reconnect_signal.wait())
                try:
                    done, pending = await asyncio.wait(
                        {stop_task, reconn_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (stop_task, reconn_task):
                        if not t.done():
                            t.cancel()
                            with suppress(asyncio.CancelledError):
                                await t
                if self._stop.is_set():
                    break
                # Half-open tripped — force a clean tear-down so the next
                # iteration opens a fresh session. Without this, the next
                # _connect() would replace self._client but the old one
                # could still hold the broker session slot.
                self.log.warning(
                    "mqtt_half_open_reconnect_triggered",
                    consecutive_failures=self._consecutive_failures,
                )
                await self._disconnect()
                self._consecutive_failures = 0
                # Small grace period so we don't immediately re-grab a
                # session the broker is still tearing down on its side.
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self.log.warning("mqtt_connection_lost", error=str(e), retry_in_s=backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, settings.mqtt_max_backoff)

    async def _connect(self) -> None:
        """Open the broker connection. Lazy-imports aiomqtt so the rest
        of the codebase doesn't require it installed."""
        try:
            import aiomqtt
        except ImportError:
            self.log.error(
                "aiomqtt_not_installed",
                hint="pip install aiomqtt — required for MQTT publishing",
            )
            # Sleep so the supervisor's reconnect loop doesn't spin.
            await asyncio.sleep(60)
            raise

        tls_context: ssl.SSLContext | None = None
        if self.tls_enabled:
            tls_context = ssl.create_default_context()
            if self.ca_cert_path:
                tls_context.load_verify_locations(cafile=self.ca_cert_path)
            if self.client_cert_path and self.client_key_path:
                tls_context.load_cert_chain(
                    certfile=self.client_cert_path,
                    keyfile=self.client_key_path,
                )

        self._client = aiomqtt.Client(
            hostname=self.broker_host,
            port=self.broker_port,
            identifier=self.client_id,
            tls_context=tls_context,
            username=self.username or None,
            password=self.password or None,
            keepalive=settings.mqtt_keepalive,
        )
        await self._client.__aenter__()
        self._connected = True
        self.log.info("mqtt_connected", broker=f"{self.broker_host}:{self.broker_port}")

    async def _disconnect(self) -> None:
        if self._client is None:
            return
        with suppress(Exception):
            await self._client.__aexit__(None, None, None)
        self._client = None
        self._connected = False

    # ──────────────────────────────────────────────────────────────────
    # Publish API
    # ──────────────────────────────────────────────────────────────────

    async def publish_telemetry(
        self,
        asset_id: str,
        metric: str,
        value: float,
        unit: str,
        source: str,
    ) -> None:
        await self._publish(
            topic=topic_map.telemetry(self.site_id, asset_id, metric),
            envelope_type="telemetry",
            source=source,
            asset_id=asset_id,
            payload={"metric": metric, "value": value, "unit": unit},
        )

    async def publish_state(
        self,
        asset_id: str,
        key: str,
        state_value: str,
        source: str = "internal",
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"key": key, "state": state_value}
        if extra:
            payload.update(extra)
        await self._publish(
            topic=topic_map.state(self.site_id, asset_id, key),
            envelope_type="state",
            source=source,
            asset_id=asset_id,
            payload=payload,
        )

    async def publish_event(
        self,
        asset_id: str,
        event_class: str,
        payload: dict[str, Any],
        source: str,
    ) -> None:
        await self._publish(
            topic=topic_map.event(self.site_id, asset_id, event_class),
            envelope_type="event",
            source=source,
            asset_id=asset_id,
            payload=payload,
        )

    async def publish_alert(
        self,
        asset_id: str,
        severity: str,
        payload: dict[str, Any],
    ) -> None:
        await self._publish(
            topic=topic_map.alert(self.site_id, asset_id, severity),
            envelope_type="alert",
            source="alert_engine",
            asset_id=asset_id,
            payload=payload,
        )

    async def publish_heartbeat(self, asset_id: str) -> None:
        await self._publish(
            topic=topic_map.heartbeat(self.site_id, asset_id),
            envelope_type="heartbeat",
            source="internal",
            asset_id=asset_id,
            payload={"timestamp": datetime.now(UTC).isoformat()},
        )

    # ──────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────

    async def _publish(
        self,
        topic: str,
        envelope_type: str,
        source: str,
        asset_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Build the envelope and publish. Fire-and-forget on error —
        the cloud is not allowed to block local alarming."""
        if not self._connected or self._client is None:
            self.log.debug("mqtt_publish_skipped_not_connected", topic=topic)
            return

        envelope = {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "ts": datetime.now(UTC).isoformat(),
            "site_id": self.site_id,
            "asset_id": asset_id,
            "type": envelope_type,
            "source": source,
            "payload": payload,
        }

        try:
            # Hard timeout — a half-open TCP socket can otherwise hang
            # the publish() call until the OS keepalive eventually fires
            # (minutes), blocking the scheduler loop that awaited it.
            await asyncio.wait_for(
                self._client.publish(
                    topic=topic,
                    payload=json.dumps(envelope, default=str).encode("utf-8"),
                    qos=self.qos,
                    retain=False,
                ),
                timeout=settings.mqtt_publish_timeout,
            )
            self._consecutive_failures = 0
            self._last_successful_publish = datetime.now(UTC)
            self.log.debug("mqtt_published", topic=topic, type=envelope_type)
        except Exception as e:
            # Never let an MQTT failure interrupt the scheduler.
            self._consecutive_failures += 1
            self.log.warning(
                "mqtt_publish_failed",
                topic=topic,
                error=str(e),
                consecutive=self._consecutive_failures,
                is_timeout=isinstance(e, TimeoutError),
            )
            # Half-open detection: paho's TCP layer may believe the
            # session is alive while the broker has silently evicted us.
            # After N consecutive failures, trip the supervisor so it
            # tears down + reconnects. Mark _connected=False immediately
            # so subsequent publishes skip cleanly until reconnected.
            if self._consecutive_failures >= settings.mqtt_publish_failure_threshold:
                self.log.error(
                    "mqtt_half_open_detected",
                    consecutive=self._consecutive_failures,
                    threshold=settings.mqtt_publish_failure_threshold,
                )
                self._connected = False
                self._reconnect_signal.set()


# ──────────────────────────────────────────────────────────────────────────
# Smoke-test entry point — verifies cert chain + topic flow end-to-end
# ──────────────────────────────────────────────────────────────────────────
async def _smoke_main() -> None:
    """Publish a few test messages and exit.

    Useful for verifying the cert chain works against AWS IoT Core
    before letting the full scheduler use this publisher.

    Usage on the Pi (after `terraform apply` and pushing certs):
        python3 -m src.integrations.mqtt_publisher

    Reads broker config from .env (same vars the scheduler uses).
    """
    import logging

    logging.basicConfig(level=logging.INFO)

    publisher = MQTTPublisher()
    print(f"Connecting to {publisher.broker_host}:{publisher.broker_port} (TLS={publisher.tls_enabled})")
    await publisher.start()

    # Give the supervisor a moment to connect.
    for _ in range(30):
        if publisher.connected:
            break
        await asyncio.sleep(0.5)
    if not publisher.connected:
        print("ERROR: failed to connect within 15s. Check broker host, port, TLS, cert paths.")
        await publisher.stop()
        return

    print("Connected. Publishing a heartbeat + one of each envelope type...")
    await publisher.publish_heartbeat("RTU-01")
    await publisher.publish_telemetry(
        asset_id="RTU-01",
        metric="suction_pressure",
        value=485.2,
        unit="PSI",
        source="smoke-test",
    )
    await publisher.publish_state(
        asset_id="RTU-01",
        key="reachability",
        state_value="up",
        source="smoke-test",
    )
    await publisher.publish_event(
        asset_id="RTU-01",
        event_class="dnp3",
        payload={"point_index": 1, "metric": "high_pressure_alarm", "value": True},
        source="smoke-test",
    )
    await publisher.publish_alert(
        asset_id="RTU-01",
        severity="critical",
        payload={"id": "ALT-SMOKE01", "message": "smoke test alarm", "status": "open"},
    )

    print(f"Done. Verify in the IoT Core MQTT test client by subscribing to aevus/{publisher.site_id}/#")
    await asyncio.sleep(2)
    await publisher.stop()


if __name__ == "__main__":
    asyncio.run(_smoke_main())
