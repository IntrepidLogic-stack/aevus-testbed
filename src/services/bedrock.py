"""Aevus AI — Bedrock service layer (extracted from api/ai.py, M3).

The model registry, per-provider invoke adapters, and the safety-aware
classify/route plumbing. The API router (src/api/ai.py) stays thin: request
models, prompts, context builders, and endpoints.

Note: the runtime client is created ONCE and reused (the router previously
built a new boto3 client per request — ARCHITECTURE_REVIEW H5).
"""

from __future__ import annotations

import json

MODELS = {
    "nova-micro": {
        "id": "us.amazon.nova-micro-v1:0",
        "provider": "amazon",
        "api": "nova",
        "label": "Nova Micro",
        "tier": 0,
        "cost_1k": 0.018,
    },
    "haiku": {
        "id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "provider": "anthropic",
        "api": "anthropic",
        "label": "Haiku 4.5",
        "tier": 1,
        "cost_1k": 0.06,
    },
    "sonnet": {
        "id": "us.anthropic.claude-sonnet-4-6",
        "provider": "anthropic",
        "api": "anthropic",
        "label": "Sonnet 4.6",
        "tier": 2,
        "cost_1k": 0.15,
    },
    "opus": {
        "id": "us.anthropic.claude-opus-4-7",
        "provider": "anthropic",
        "api": "anthropic",
        "label": "Opus 4.7",
        "tier": 3,
        "cost_1k": 0.75,
    },
    "nemotron-9b": {
        "id": "nvidia.nemotron-nano-9b-v2",
        "provider": "nvidia",
        "api": "converse",
        "label": "Nemotron 9B",
        "tier": 1,
        "cost_1k": 0.02,
    },
    "nemotron-12b": {
        "id": "nvidia.nemotron-nano-12b-v2",
        "provider": "nvidia",
        "api": "converse",
        "label": "Nemotron 12B VL",
        "tier": 1,
        "cost_1k": 0.03,
    },
    "nemotron-30b": {
        "id": "nvidia.nemotron-nano-3-30b",
        "provider": "nvidia",
        "api": "converse",
        "label": "Nemotron 30B",
        "tier": 2,
        "cost_1k": 0.05,
    },
    "nova-pro": {
        "id": "us.amazon.nova-pro-v1:0",
        "provider": "amazon",
        "api": "nova",
        "label": "Nova Pro",
        "tier": 2,
        "cost_1k": 0.08,
    },
}

CLASSIFY_PROMPT = """Classify this operator query into exactly one category. Reply with ONLY the category word:
- CHAT: casual question, greeting, simple status check
- ANALYSIS: root cause, trend analysis, comparison, "why", "analyze", "compare"
- SAFETY: anything involving safety, interlocks, H2S, LEL, ESD, emergency, ISA-18.2 compliance
- REPORT: shift handover, summary, export, compliance report
- NAVIGATE: "show me", "go to", "open", navigation request

Query: {query}"""


# Lazily-created singleton Bedrock runtime client (H5: was per-request).
_client = None


def _get_client():
    """Return the shared bedrock-runtime client, creating it on first use."""
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("bedrock-runtime", region_name="us-east-1")
    return _client


def _invoke_anthropic(client, model_id: str, system: str, user_msg: str, max_tokens: int = 400) -> str:
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        }
    )
    r = client.invoke_model(modelId=model_id, contentType="application/json", accept="application/json", body=body)
    return json.loads(r["body"].read())["content"][0]["text"]


def _invoke_nova(client, model_id: str, system: str, user_msg: str, max_tokens: int = 400) -> str:
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": [{"text": f"{system}\n\n{user_msg}"}]}],
            "inferenceConfig": {"maxTokens": max_tokens},
        }
    )
    r = client.invoke_model(modelId=model_id, contentType="application/json", accept="application/json", body=body)
    return json.loads(r["body"].read())["output"]["message"]["content"][0]["text"]


def _invoke_converse(client, model_id: str, system: str, user_msg: str, max_tokens: int = 400) -> str:
    r = client.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    return r["output"]["message"]["content"][0]["text"]


def _invoke_model(client, model_key: str, system: str, user_msg: str, max_tokens: int = 400) -> str:
    m = MODELS[model_key]
    if m["api"] == "anthropic":
        return _invoke_anthropic(client, m["id"], system, user_msg, max_tokens)
    elif m["api"] == "nova":
        return _invoke_nova(client, m["id"], system, user_msg, max_tokens)
    elif m["api"] == "converse":
        return _invoke_converse(client, m["id"], system, user_msg, max_tokens)
    raise ValueError(f"Unknown API type: {m['api']}")


def _classify_query(client, query: str) -> str:
    """Use Nova Micro for ultra-fast query classification."""
    try:
        result = _invoke_nova(client, MODELS["nova-micro"]["id"], "", CLASSIFY_PROMPT.format(query=query), 10)
        cat = result.strip().upper().split()[0] if result.strip() else "CHAT"
        if cat in ("CHAT", "ANALYSIS", "SAFETY", "REPORT", "NAVIGATE"):
            return cat
        return "CHAT"
    except Exception:
        return "CHAT"


def _route_model(classification: str, force_model: str | None = None) -> tuple[str, str]:
    """Safety-aware SCADA model routing (Patent Pending #7)."""
    if force_model and force_model in MODELS:
        return force_model, f"forced:{force_model}"

    routing = {
        "CHAT": ("haiku", "real-time chat → Haiku 4.5"),
        "ANALYSIS": ("sonnet", "analysis query → Sonnet 4.6"),
        "SAFETY": ("sonnet", "safety-critical → Sonnet 4.6 (ISA-18.2 mandate)"),
        "REPORT": ("sonnet", "report generation → Sonnet 4.6"),
        "NAVIGATE": ("haiku", "navigation intent → Haiku 4.5"),
    }
    return routing.get(classification, ("haiku", "default → Haiku 4.5"))
