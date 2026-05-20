"""End-to-end test of the RCA Lambda with all AWS clients mocked.

Catches Lambda bugs locally so we don't pay for an AWS invocation to
find out the IoT publish call has the wrong arg shape, the S3 key
template is malformed, or the latency calculator rejects the iso
timestamp our publisher emits.

Coverage:
  • happy-path: fixture in → Bedrock returns valid JSON →
    narrative published + audited + latency computed
  • Bedrock failure → deterministic fallback narrative published
  • S3 list failure during context gathering → handler still runs
  • Malformed envelope → handler rejects with 400
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Lambda env vars handler.py reads at import time.
os.environ.setdefault("AUDIT_BUCKET", "test-audit-bucket")
os.environ.setdefault("IOT_ENDPOINT", "test-endpoint.iot.us-east-2.amazonaws.com")
os.environ.setdefault("BEDROCK_MODEL_ID", "anthropic.claude-test")

# boto3 isn't installed in dev — it's provided by the Lambda runtime.
# Stub it before handler.py imports, so the module loads cleanly. The
# stub exposes `client()` returning fresh MagicMocks; tests retrieve
# the same instances via the module's `bedrock`/`iot_data`/`s3`
# globals (set at module-import time by `boto3.client(...)`).
if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *a, **k: MagicMock(name=f"{a[0] if a else 'unknown'}-mock")
    sys.modules["boto3"] = boto3_stub

if "botocore" not in sys.modules:
    botocore = types.ModuleType("botocore")
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = lambda **kw: MagicMock(name="Config-mock")
    botocore_exceptions = types.ModuleType("botocore.exceptions")

    class _FakeClientError(Exception):
        def __init__(self, response, operation_name):
            self.response = response
            self.operation_name = operation_name
            super().__init__(response.get("Error", {}).get("Message", "client error"))

    class _FakeBotoCoreError(Exception):
        pass

    botocore_exceptions.ClientError = _FakeClientError
    botocore_exceptions.BotoCoreError = _FakeBotoCoreError
    sys.modules["botocore"] = botocore
    sys.modules["botocore.config"] = botocore_config
    sys.modules["botocore.exceptions"] = botocore_exceptions


RCA_DIR = Path(__file__).parent.parent.parent / "infra" / "lambda" / "rca"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(RCA_DIR))


@pytest.fixture(scope="module")
def handler_module():
    import handler  # noqa: E402  (deferred until stubs are in place)
    yield handler


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _good_bedrock_response() -> dict:
    """Bedrock invoke_model response shape — a Body stream wrapping
    a JSON blob, where Claude's text content is a list of blocks."""
    body_payload = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "probable_cause": "Discharge pressure spike from downstream valve closure.",
                    "evidence": [
                        "high_pressure_alarm asserted at 14:32:05Z",
                        "discharge_pressure 1442 PSI > 1400 critical threshold",
                        "no comm_fault in window",
                    ],
                    "severity": "critical",
                    "recommended_action": (
                        "Dispatch field technician to inspect downstream valve V-103 "
                        "before any restart."
                    ),
                    "confidence": 0.87,
                    "supporting_assets": ["RTU-01"],
                }),
            }
        ],
    }
    stream = MagicMock()
    stream.read.return_value = json.dumps(body_payload).encode("utf-8")
    return {"body": stream}


class TestHappyPath:
    def test_handler_publishes_narrative_and_audits(self, handler_module):
        # Reset all the module-level client mocks so we can assert
        # call counts cleanly per test.
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        handler_module.bedrock.invoke_model.return_value = _good_bedrock_response()
        # Context gathering: stub S3 list/get to return empty (the
        # prompt renderer handles missing events gracefully).
        handler_module.s3.list_objects_v2.return_value = {"Contents": []}

        event = _load_fixture("critical_high_pressure.json")
        result = handler_module.lambda_handler(event, MagicMock())

        # Status + tracing fields.
        assert result["statusCode"] == 200
        assert result["alert_id"] == "ALT-HIGHPRES01"
        assert isinstance(result["duration_ms"], int)
        # Latency is bounded — the fixture's detected_at is in the past
        # relative to "now", so the value is positive.
        assert result["latency_ms_alert_to_rca"] is not None
        assert result["latency_ms_alert_to_rca"] >= 0

        # IoT publish to the expected topic.
        publish_kwargs = handler_module.iot_data.publish.call_args.kwargs
        assert publish_kwargs["topic"] == "aevus/lab/RTU-01/rca/ALT-HIGHPRES01"
        payload = json.loads(publish_kwargs["payload"])
        assert payload["rca"]["probable_cause"].startswith("Discharge pressure")
        assert payload["rca"]["confidence"] == 0.87
        assert payload["model_id"] == os.environ["BEDROCK_MODEL_ID"]

        # S3 audit write under rca/ prefix.
        s3_kwargs = handler_module.s3.put_object.call_args.kwargs
        assert s3_kwargs["Bucket"] == "test-audit-bucket"
        assert s3_kwargs["Key"].startswith("rca/lab/RTU-01/")
        assert s3_kwargs["Key"].endswith(".json")

    def test_link_down_fixture(self, handler_module):
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        handler_module.bedrock.invoke_model.return_value = _good_bedrock_response()
        handler_module.s3.list_objects_v2.return_value = {"Contents": []}

        event = _load_fixture("critical_link_down.json")
        result = handler_module.lambda_handler(event, MagicMock())

        assert result["statusCode"] == 200
        publish_kwargs = handler_module.iot_data.publish.call_args.kwargs
        # Topic must reflect the SW-01 asset from the fixture.
        assert publish_kwargs["topic"] == "aevus/lab/SW-01/rca/ALT-LNKDOWN03"


class TestBedrockFailureFallback:
    def test_bedrock_throws_emits_deterministic_narrative(self, handler_module):
        """When Bedrock fails entirely, we still emit a structured
        RCA so the audit trail isn't blank."""
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        handler_module.bedrock.invoke_model.side_effect = RuntimeError("throttled")
        handler_module.s3.list_objects_v2.return_value = {"Contents": []}

        event = _load_fixture("critical_low_battery.json")
        result = handler_module.lambda_handler(event, MagicMock())

        assert result["statusCode"] == 200
        # The fallback narrative was published.
        payload = json.loads(handler_module.iot_data.publish.call_args.kwargs["payload"])
        assert payload["rca"]["probable_cause"].startswith("RCA unavailable")
        assert payload["rca"]["confidence"] == 0.0
        # The audit record still got written — compliance posture
        # depends on no missing narratives.
        assert handler_module.s3.put_object.called


class TestEnvelopeValidation:
    def test_missing_site_id_rejected(self, handler_module):
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        result = handler_module.lambda_handler(
            {"schema_version": "1.0", "asset_id": "RTU-01", "payload": {}},
            MagicMock(),
        )
        assert result["statusCode"] == 400
        # Neither IoT nor S3 should have been called.
        assert not handler_module.iot_data.publish.called
        assert not handler_module.s3.put_object.called

    def test_non_dict_event_rejected(self, handler_module):
        handler_module.bedrock.reset_mock()
        result = handler_module.lambda_handler("not-a-dict", MagicMock())
        assert result["statusCode"] == 400


class TestS3ContextDegrades:
    def test_s3_list_failure_does_not_abort(self, handler_module):
        """If audit-bucket listing fails, the handler should still
        produce a narrative (with empty event context)."""
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        handler_module.bedrock.invoke_model.return_value = _good_bedrock_response()
        # context.py wraps S3 calls in _safe(), which catches any
        # exception. Raise a plain RuntimeError — same outcome as a
        # real ClientError from boto.
        handler_module.s3.list_objects_v2.side_effect = RuntimeError("AccessDenied")

        event = _load_fixture("critical_unreachable.json")
        result = handler_module.lambda_handler(event, MagicMock())

        assert result["statusCode"] == 200
        assert handler_module.iot_data.publish.called


class TestLatency:
    def test_latency_negative_clock_skew_clamps_to_zero(self, handler_module):
        """An alert detected_at in the *future* (clock skew) must
        produce latency=0, not a negative number."""
        from datetime import datetime, timezone, timedelta
        handler_module.bedrock.reset_mock()
        handler_module.iot_data.reset_mock()
        handler_module.s3.reset_mock()
        handler_module.bedrock.invoke_model.return_value = _good_bedrock_response()
        handler_module.s3.list_objects_v2.return_value = {"Contents": []}

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        event = _load_fixture("critical_high_pressure.json")
        event["payload"]["detected_at"] = future

        result = handler_module.lambda_handler(event, MagicMock())
        assert result["latency_ms_alert_to_rca"] == 0
