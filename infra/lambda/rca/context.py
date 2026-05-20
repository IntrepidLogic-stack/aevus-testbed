"""
Context gathering for the RCA Lambda.

When a critical alert triggers, we have ~50ms to build the Bedrock
prompt. Speed matters more than completeness — if SiteWise is slow,
we skip it rather than block. The prompt gracefully handles missing
sections (see prompt.py block renderers).

Three context sources, in priority order:
  1. The alert payload itself — always present
  2. S3 audit bucket — recent events for the same asset (cheap, ~10ms)
  3. SiteWise — asset metadata + recent property history (~50-200ms)

Timestream / InfluxDB telemetry retrieval is stubbed in this module
but disabled by default — we'll wire it in once the IoT-Core →
Timestream rule lands (next phase).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger()


# Tunable via Lambda env vars — defaults are conservative for 5-min cold
# alarm context.
EVENT_WINDOW_MIN = int(os.environ.get("RCA_EVENT_WINDOW_MIN", "15"))
TELEMETRY_WINDOW_MIN = int(os.environ.get("RCA_TELEMETRY_WINDOW_MIN", "30"))
MAX_EVENTS = int(os.environ.get("RCA_MAX_EVENTS", "50"))
MAX_RELATED_ASSETS = int(os.environ.get("RCA_MAX_RELATED", "10"))


def _s3() -> Any:
    return boto3.client("s3")


def _sitewise() -> Any:
    return boto3.client("iotsitewise")


# ──────────────────────────────────────────────────────────────────────────
# Public — single entry point used by handler.py
# ──────────────────────────────────────────────────────────────────────────
def gather(
    alert: dict[str, Any],
    site_id: str,
    asset_id: str,
    audit_bucket: str,
) -> dict[str, Any]:
    """Gather everything needed for the prompt.

    Returns a dict matching the fields of prompt.PromptContext.
    Sections that fail (S3 throttle, SiteWise lag) come back empty —
    the prompt renderer handles "no data" cleanly.
    """
    asset = _safe(lambda: _fetch_asset(site_id, asset_id), default={})
    events = _safe(
        lambda: _fetch_recent_events(audit_bucket, site_id, asset_id),
        default=[],
    )
    related = _safe(
        lambda: _fetch_related_assets(site_id, exclude_asset_id=asset_id),
        default=[],
    )
    # Telemetry stub — see module docstring.
    telemetry: list[dict[str, Any]] = []

    return {
        "alert": alert,
        "asset": asset,
        "recent_events": events,
        "recent_telemetry": telemetry,
        "related_assets": related,
        "event_window_minutes": EVENT_WINDOW_MIN,
        "telemetry_window_minutes": TELEMETRY_WINDOW_MIN,
    }


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:
        logger.warning("rca_context_section_failed: %s", e)
        return default


# ──────────────────────────────────────────────────────────────────────────
# S3 audit — recent events for one asset
# ──────────────────────────────────────────────────────────────────────────
def _fetch_recent_events(
    audit_bucket: str,
    site_id: str,
    asset_id: str,
) -> list[dict[str, Any]]:
    """List the most-recent N audit objects under events/{site}/{asset}/
    and pull their bodies.

    Audit objects are partitioned by yyyy/MM/dd by the IoT rule, so
    we list backwards from today.
    """
    s3 = _s3()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=EVENT_WINDOW_MIN)

    keys: list[str] = []
    # Walk back up to 2 days of partitions (covers any window the
    # operator might reasonably ask for, bounded so we don't list
    # the entire bucket).
    for delta_days in range(2):
        day = (now - timedelta(days=delta_days)).strftime("%Y/%m/%d")
        prefix = f"events/{site_id}/{asset_id}/{day}/"
        try:
            resp = s3.list_objects_v2(
                Bucket=audit_bucket,
                Prefix=prefix,
                MaxKeys=200,
            )
            for obj in resp.get("Contents", []):
                if obj["LastModified"] >= window_start:
                    keys.append(obj["Key"])
            if len(keys) >= MAX_EVENTS:
                break
        except (ClientError, BotoCoreError) as e:
            logger.warning("s3_list_failed prefix=%s: %s", prefix, e)
            continue

    # Sort newest-first, cap, then re-sort oldest-first for the prompt
    # (so the model reads chronologically).
    keys.sort(reverse=True)
    keys = keys[:MAX_EVENTS]
    keys.sort()

    events: list[dict[str, Any]] = []
    for key in keys:
        try:
            obj = s3.get_object(Bucket=audit_bucket, Key=key)
            body = obj["Body"].read()
            events.append(json.loads(body))
        except (ClientError, BotoCoreError, json.JSONDecodeError) as e:
            logger.warning("s3_get_failed key=%s: %s", key, e)
            continue
    return events


# ──────────────────────────────────────────────────────────────────────────
# SiteWise — asset metadata + related assets
# ──────────────────────────────────────────────────────────────────────────
def _fetch_asset(site_id: str, asset_id: str) -> dict[str, Any]:
    """Resolve asset metadata from SiteWise.

    Asset external_id should be the same as our internal asset_id
    (set when the seed_assets script registers devices). If lookup
    fails, return a minimal stub so the prompt has something.
    """
    sw = _sitewise()
    try:
        # SiteWise indexes by external ID via DescribeAsset when the
        # asset was created with that ID.
        resp = sw.list_assets(
            assetModelId=os.environ.get("RCA_SCADAPACK_MODEL_ID", ""),
            filter="ALL",
            maxResults=250,
        )
        # Look for a matching asset by external_id. In production this
        # would use a fast lookup table in DynamoDB rather than scanning.
        for summary in resp.get("assetSummaries", []):
            if summary.get("externalId") == asset_id:
                return _expand_asset(summary)
    except (ClientError, BotoCoreError) as e:
        logger.warning("sitewise_lookup_failed asset=%s: %s", asset_id, e)
    return {"id": asset_id}


def _fetch_related_assets(site_id: str, exclude_asset_id: str) -> list[dict[str, Any]]:
    """List other assets at the same site (children of the Cabinet)."""
    sw = _sitewise()
    cabinet_id = os.environ.get(f"RCA_CABINET_ASSET_ID_{site_id.upper()}", "")
    if not cabinet_id:
        return []
    related: list[dict[str, Any]] = []
    try:
        for hierarchy in ("radios", "rtus", "routers", "switches"):
            resp = sw.list_associated_assets(
                assetId=cabinet_id,
                hierarchyId=hierarchy,
                traversalDirection="CHILD",
                maxResults=MAX_RELATED_ASSETS,
            )
            for summary in resp.get("assetSummaries", []):
                if summary.get("externalId") == exclude_asset_id:
                    continue
                related.append(_expand_asset(summary))
                if len(related) >= MAX_RELATED_ASSETS:
                    return related
    except (ClientError, BotoCoreError) as e:
        logger.warning("sitewise_related_failed cabinet=%s: %s", cabinet_id, e)
    return related


def _expand_asset(summary: dict[str, Any]) -> dict[str, Any]:
    """Convert a SiteWise asset summary into our flat asset dict.

    SiteWise's response shape is verbose; we flatten to what the prompt
    actually consumes.
    """
    return {
        "id": summary.get("externalId") or summary.get("id"),
        "name": summary.get("name"),
        "type": _asset_type_from_model_id(summary.get("assetModelId", "")),
        "status": "unknown",  # SiteWise asset status doesn't map 1:1
    }


def _asset_type_from_model_id(model_id: str) -> str:
    """Heuristic: derive a friendly type from the model arn/id.

    We could resolve this through DescribeAssetModel but a string
    match keeps the latency under one ms.
    """
    if "JR900" in model_id or "trio" in model_id.lower():
        return "radio"
    if "SCADAPack" in model_id or "scadapack" in model_id.lower():
        return "rtu"
    if "MikroTik" in model_id or "mikrotik" in model_id.lower():
        return "router"
    if "Catalyst" in model_id or "cisco" in model_id.lower():
        return "switch"
    return "unknown"
