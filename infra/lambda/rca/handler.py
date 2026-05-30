"""
Aevus Bedrock RCA Lambda — patent-relevant AI on real-time events.

Trigger: IoT Core topic rule on `aevus/+/+/alerts/critical`.
Output:  Publish a structured RCA narrative back to
         `aevus/{site_id}/{asset_id}/rca/{alert_id}` and append the
         same narrative to S3 audit (immutable record).

Flow (target end-to-end latency: <3 seconds from alert → narrative):
  1. Parse the inbound IoT event (it's the MQTT payload, JSON).
  2. Gather context: asset metadata, recent events, related assets.
  3. Render the system + user prompts (prompt.py).
  4. Invoke Bedrock — Claude Sonnet (configurable model via env).
  5. Parse + validate Claude's response.
  6. Publish back to MQTT, append to S3 audit, return for tracing.

Defense in depth:
  • Every external call has a timeout + try/except. A failed RCA
    NEVER affects local alarming on the Pi — the alarm already
    landed in the dashboard before this Lambda was even invoked.
  • Bedrock failures fall back to a deterministic "RCA unavailable,
    investigate manually" narrative so the audit trail isn't blank.
  • The Lambda has a dead-letter SQS queue (wired in Terraform) for
    invocations that fail entirely.

Patent (P-008) positioning:
  Every successful RCA narrative is logged with the original alert's
  detection_at + the narrative's generated_at. The delta is the
  end-to-end "AI knew before the operator" metric we cite in the
  patent provisional + UXDA submission.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from context import gather
from prompt import PromptContext, parse_response, render

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# ── Configuration (Lambda env vars) ─────────────────────────────────────
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    # Haiku for primary — sub-2s warm latency, sufficient reasoning for
    # threshold-based RCA narratives. Sonnet as fallback when Haiku throttles,
    # cold-starts long, or returns malformed JSON.
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
BEDROCK_FALLBACK_MODEL_ID = os.environ.get(
    "BEDROCK_FALLBACK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-east-2"))
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1024"))
BEDROCK_TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.2"))
BEDROCK_TIMEOUT_S = int(os.environ.get("BEDROCK_TIMEOUT_S", "20"))

AUDIT_BUCKET = os.environ["AUDIT_BUCKET"]  # required, raises on cold start if missing
IOT_ENDPOINT = os.environ["IOT_ENDPOINT"]  # required
RCA_TOPIC_TEMPLATE = "aevus/{site_id}/{asset_id}/rca/{alert_id}"


# ── Boto clients — module-level for warm-invocation reuse ───────────────
_bedrock_config = Config(
    read_timeout=BEDROCK_TIMEOUT_S,
    connect_timeout=5,
    retries={"max_attempts": 2, "mode": "standard"},
)
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION, config=_bedrock_config)
iot_data = boto3.client("iot-data", endpoint_url=f"https://{IOT_ENDPOINT}")
s3 = boto3.client("s3")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """IoT Core rule action handler.

    `event` is the MQTT payload as the IoT rule passes it. We get the
    envelope our Pi-side publisher emits.
    """
    start_time = time.time()
    logger.info("rca_invoked event=%s", json.dumps(event)[:512])

    try:
        envelope = _parse_envelope(event)
    except ValueError as e:
        logger.error("rca_envelope_invalid: %s", e)
        return {"statusCode": 400, "error": str(e)}

    site_id = envelope["site_id"]
    asset_id = envelope["asset_id"]
    alert = envelope.get("payload", {})
    alert_id = alert.get("id", f"unknown-{int(start_time * 1000)}")

    (
        logger.bind(  # structlog-style isn't available; mimic with extra
            # noqa — structured logging in stdlib via 'extra' kwarg
        )
        if False
        else logger
    )  # keep simple — we just include keys in messages

    logger.info(
        "rca_processing alert_id=%s asset_id=%s site=%s",
        alert_id,
        asset_id,
        site_id,
    )

    # Build context. _safe inside gather() ensures partial-failures
    # never raise to here.
    ctx_dict = gather(
        alert=alert,
        site_id=site_id,
        asset_id=asset_id,
        audit_bucket=AUDIT_BUCKET,
    )
    ctx = PromptContext(**ctx_dict)
    system_prompt, user_prompt = render(ctx)

    # Invoke Bedrock.
    try:
        rca = _invoke_bedrock(system_prompt, user_prompt)
    except Exception as e:
        logger.exception("rca_bedrock_failed: %s", e)
        rca = _fallback_narrative(str(e))

    # Annotate with the latency we care about for the patent.
    narrative_at = datetime.now(UTC).isoformat()
    detected_at = alert.get("detected_at")
    latency_ms = _compute_latency_ms(detected_at, narrative_at)

    output = {
        "alert_id": alert_id,
        "asset_id": asset_id,
        "site_id": site_id,
        "rca": rca,
        "detected_at": detected_at,
        "generated_at": narrative_at,
        "latency_ms_alert_to_rca": latency_ms,
        "model_id": BEDROCK_MODEL_ID,
    }
    logger.info(
        "rca_complete alert_id=%s asset=%s confidence=%.2f latency_ms=%s",
        alert_id,
        asset_id,
        rca.get("confidence", 0.0),
        latency_ms,
    )

    # Publish to MQTT for the dashboard + write to S3 audit.
    _publish_rca(site_id, asset_id, alert_id, output)
    _write_audit(site_id, asset_id, alert_id, output)

    return {
        "statusCode": 200,
        "duration_ms": int((time.time() - start_time) * 1000),
        "alert_id": alert_id,
        "latency_ms_alert_to_rca": latency_ms,
    }


# ──────────────────────────────────────────────────────────────────────────
# Envelope parsing
# ──────────────────────────────────────────────────────────────────────────
def _parse_envelope(event: dict[str, Any]) -> dict[str, Any]:
    """The IoT rule passes the MQTT JSON payload as the Lambda event.

    Confirm the envelope shape we publish from src/integrations/
    mqtt_publisher.py — schema_version + site_id + asset_id + payload.
    """
    if not isinstance(event, dict):
        raise ValueError(f"event is not a dict: {type(event).__name__}")
    if event.get("schema_version") != "1.0":
        # Be tolerant for now; log so we notice if the contract drifts.
        logger.warning("rca_unexpected_schema_version: %s", event.get("schema_version"))
    if "site_id" not in event or "asset_id" not in event:
        raise ValueError("envelope missing site_id or asset_id")
    return event


# ──────────────────────────────────────────────────────────────────────────
# Bedrock invocation
# ──────────────────────────────────────────────────────────────────────────
def _invoke_bedrock(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Invoke Claude via Bedrock with primary→fallback model chain.

    Try BEDROCK_MODEL_ID (Haiku) first for low latency. On failure
    (throttling, model degradation, malformed response), fall through
    to BEDROCK_FALLBACK_MODEL_ID (Sonnet) — slower but more capable.
    Only if BOTH fail does the caller fall through to the deterministic
    _fallback_narrative.

    Logs the model actually used + whether fallback was triggered, so
    the latency widget can distinguish primary-path P95 from
    fallback-path P95 over time."""
    last_err: Exception | None = None
    for attempt, model_id in enumerate([BEDROCK_MODEL_ID, BEDROCK_FALLBACK_MODEL_ID]):
        if attempt > 0:
            logger.warning(
                "rca_bedrock_fallback_to model=%s primary_error=%s",
                model_id,
                str(last_err)[:200],
            )
        try:
            result = _invoke_one_model(system_prompt, user_prompt, model_id)
            result["_model_used"] = model_id
            result["_fallback_triggered"] = attempt > 0
            return result
        except Exception as e:  # noqa: BLE001 — we want to catch *anything* here
            last_err = e
            logger.warning(
                "rca_bedrock_attempt_failed model=%s err=%s",
                model_id,
                str(e)[:200],
            )
            continue
    # Both models failed — re-raise so caller falls back to deterministic narrative
    assert last_err is not None
    raise last_err


def _invoke_one_model(system_prompt: str, user_prompt: str, model_id: str) -> dict[str, Any]:
    """Single Bedrock invocation for one specific model. Raises on any failure."""
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": BEDROCK_MAX_TOKENS,
        "temperature": BEDROCK_TEMPERATURE,
        "system": system_prompt,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
    }
    resp = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    text_parts = [block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text"]
    raw_text = "".join(text_parts).strip()
    if not raw_text:
        raise RuntimeError(f"Bedrock model {model_id} returned no text content")
    return parse_response(raw_text)


def _fallback_narrative(error: str) -> dict[str, Any]:
    """When Bedrock fails entirely, we still emit a structured RCA
    so the audit trail isn't blank and the dashboard has something
    to render. The operator sees this and knows to investigate
    manually."""
    return {
        "probable_cause": "RCA unavailable — Bedrock invocation failed",
        "evidence": [f"Bedrock error: {error[:200]}"],
        "severity": "info",
        "recommended_action": (
            "Investigate the alarm manually. The Aevus RCA service was "
            "unable to generate a narrative for this event. Local "
            "alarming and threshold detection were unaffected."
        ),
        "confidence": 0.0,
        "supporting_assets": [],
    }


# ──────────────────────────────────────────────────────────────────────────
# Output — MQTT + S3
# ──────────────────────────────────────────────────────────────────────────
def _publish_rca(
    site_id: str,
    asset_id: str,
    alert_id: str,
    output: dict[str, Any],
) -> None:
    topic = RCA_TOPIC_TEMPLATE.format(site_id=site_id, asset_id=asset_id, alert_id=alert_id)
    try:
        iot_data.publish(
            topic=topic,
            qos=1,
            payload=json.dumps(output, default=str),
        )
        logger.info("rca_published topic=%s", topic)
    except (ClientError, BotoCoreError) as e:
        logger.error("rca_publish_failed topic=%s: %s", topic, e)


def _write_audit(
    site_id: str,
    asset_id: str,
    alert_id: str,
    output: dict[str, Any],
) -> None:
    """Append the RCA to the audit bucket alongside the original
    alert + event records. Object Lock makes this evidence
    tamper-evident."""
    now = datetime.now(UTC)
    key = f"rca/{site_id}/{asset_id}/{now.strftime('%Y/%m/%d')}/{now.strftime('%H-%M-%S-%f')}-{alert_id}.json"
    try:
        s3.put_object(
            Bucket=AUDIT_BUCKET,
            Key=key,
            Body=json.dumps(output, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("rca_audit_written key=%s", key)
    except (ClientError, BotoCoreError) as e:
        logger.error("rca_audit_failed key=%s: %s", key, e)


# ──────────────────────────────────────────────────────────────────────────
# Latency
# ──────────────────────────────────────────────────────────────────────────
def _compute_latency_ms(detected_at_iso: str | None, narrative_at_iso: str) -> int | None:
    if not detected_at_iso:
        return None
    try:
        detected = datetime.fromisoformat(detected_at_iso.replace("Z", "+00:00"))
        narrative = datetime.fromisoformat(narrative_at_iso.replace("Z", "+00:00"))
        delta_ms = int((narrative - detected).total_seconds() * 1000)
        return max(0, delta_ms)
    except (ValueError, TypeError) as e:
        logger.warning("rca_latency_parse_failed: %s", e)
        return None
