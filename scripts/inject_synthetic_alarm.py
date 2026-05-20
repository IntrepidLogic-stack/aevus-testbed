#!/usr/bin/env python3
"""Inject a synthetic critical alarm onto MQTT for end-to-end testing.

Publishes a fixture envelope to the appropriate aevus/<site>/<asset>/
alerts/critical topic so the full chain — MQTT → IoT Core rule →
Bedrock RCA Lambda → RCA topic → dashboard — can be exercised
without waiting on a real lab event.

Usage:
    # Against local Mosquitto:
    python scripts/inject_synthetic_alarm.py \
        --broker localhost --port 1883 \
        --fixture tests/lambda/fixtures/critical_high_pressure.json

    # Against AWS IoT Core (TLS + cert):
    python scripts/inject_synthetic_alarm.py \
        --broker <endpoint>-ats.iot.us-east-2.amazonaws.com --port 8883 --tls \
        --ca-cert ~/aevus-testbed/.certs/AmazonRootCA1.pem \
        --client-cert ~/aevus-testbed/.certs/aevus-edge-lab-01.cert.pem \
        --client-key  ~/aevus-testbed/.certs/aevus-edge-lab-01.key.pem \
        --fixture tests/lambda/fixtures/critical_high_pressure.json

The fixture's site_id + asset_id determine the destination topic.
Pass --override-asset / --override-site to retarget a fixture at a
different device.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", required=True, type=Path,
                   help="Path to a JSON fixture (see tests/lambda/fixtures/).")
    p.add_argument("--broker", default="localhost",
                   help="MQTT broker hostname.")
    p.add_argument("--port", type=int, default=1883,
                   help="MQTT broker port (1883 plain, 8883 TLS).")
    p.add_argument("--tls", action="store_true",
                   help="Connect with TLS (required for IoT Core).")
    p.add_argument("--ca-cert", type=Path,
                   help="CA bundle (Amazon Root CA for IoT Core).")
    p.add_argument("--client-cert", type=Path,
                   help="X.509 client cert (IoT Core auth).")
    p.add_argument("--client-key", type=Path,
                   help="X.509 client key (IoT Core auth).")
    p.add_argument("--client-id", default="aevus-synth-injector",
                   help="MQTT client ID.")
    p.add_argument("--override-asset", default=None,
                   help="Override asset_id from the fixture.")
    p.add_argument("--override-site", default=None,
                   help="Override site_id from the fixture.")
    p.add_argument("--restamp", action="store_true",
                   help="Set ts and detected_at to now() before publishing.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be published and exit.")
    return p.parse_args()


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _apply_overrides(env: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply CLI overrides + optional restamping in place."""
    if args.override_site:
        env["site_id"] = args.override_site
    if args.override_asset:
        env["asset_id"] = args.override_asset
        if isinstance(env.get("payload"), dict):
            env["payload"]["asset_id"] = args.override_asset
    if args.restamp:
        now_iso = datetime.now(timezone.utc).isoformat()
        env["ts"] = now_iso
        if isinstance(env.get("payload"), dict):
            env["payload"]["detected_at"] = now_iso
    return env


def _topic_for(envelope: dict[str, Any]) -> str:
    site = envelope["site_id"]
    asset = envelope["asset_id"]
    severity = envelope.get("payload", {}).get("severity", "critical")
    return f"aevus/{site}/{asset}/alerts/{severity}"


async def _publish(envelope: dict[str, Any], topic: str, args: argparse.Namespace) -> None:
    import aiomqtt

    tls_context: Optional[ssl.SSLContext] = None
    if args.tls:
        tls_context = ssl.create_default_context()
        if args.ca_cert:
            tls_context.load_verify_locations(cafile=str(args.ca_cert))
        if args.client_cert and args.client_key:
            tls_context.load_cert_chain(
                certfile=str(args.client_cert),
                keyfile=str(args.client_key),
            )

    print(f"→ Connecting to {args.broker}:{args.port} (TLS={args.tls})...")
    async with aiomqtt.Client(
        hostname=args.broker,
        port=args.port,
        identifier=args.client_id,
        tls_context=tls_context,
    ) as client:
        payload = json.dumps(envelope, default=str).encode("utf-8")
        print(f"→ Publishing to: {topic}")
        print(f"→ Payload:       {payload[:200].decode()}{'...' if len(payload) > 200 else ''}")
        await client.publish(topic=topic, payload=payload, qos=1)
        print("✓ Published.")


def main() -> int:
    args = _parse_args()

    if not args.fixture.exists():
        print(f"ERROR: fixture not found: {args.fixture}", file=sys.stderr)
        return 1

    envelope = _apply_overrides(_load_fixture(args.fixture), args)
    topic = _topic_for(envelope)

    if args.dry_run:
        print(f"DRY RUN — would publish to {topic}")
        print(json.dumps(envelope, indent=2, default=str))
        return 0

    try:
        asyncio.run(_publish(envelope, topic, args))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
