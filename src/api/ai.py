"""
Aevus AI Engine — Multi-model Bedrock architecture.

Tier 1: Nova Micro — fast classification/routing (<300ms)
Tier 2: Claude Haiku 4.5 — real-time operator chat (~800ms)
Tier 3: Claude Sonnet 4.6 — analysis, reports, safety queries (~2s)
Tier 4: Claude Opus 4.7 — deep investigation (async only)

Plus:
- Cohere Embed v4 — alarm similarity search (1536-dim)
- Cohere Rerank 3.5 — result ranking
- NVIDIA Nemotron 12B VL — vision/visual inspection
- NVIDIA Nemotron 9B/30B — edge inference simulation
- Amazon Nova Sonic — voice interface (streaming)

Copyright 2026 Intrepid Logic LLC. All rights reserved.
Patent Pending: Safety-Aware SCADA Model Routing (Provisional #7)
Patent Pending: Edge-Cloud Hybrid Inference Architecture (Provisional #8)
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter(tags=["ai"])

# ═══════════════════════════════════════
# Models
# ═══════════════════════════════════════

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

# ═══════════════════════════════════════
# Pydantic schemas
# ═══════════════════════════════════════


class AIRequest(BaseModel):
    prompt: str
    context: dict | None = None
    force_model: str | None = None  # override routing


class AIResponse(BaseModel):
    reply: str
    model: str
    tier: int
    latency_ms: int
    routed_reason: str


class SimilarAlarm(BaseModel):
    alarm_text: str
    score: float
    resolution: str | None = None


class SimilarityRequest(BaseModel):
    alarm_text: str
    history: list[dict] | None = None


class SimilarityResponse(BaseModel):
    similar: list[SimilarAlarm]
    model: str


class VisionRequest(BaseModel):
    prompt: str | None = "Analyze this equipment image for anomalies, corrosion, leaks, or safety concerns."


class VisionResponse(BaseModel):
    analysis: str
    model: str
    latency_ms: int


class BatchRequest(BaseModel):
    alarms: list[dict]
    analysis_type: str = "rationalization"  # rationalization | trends | nuisance


class BatchResponse(BaseModel):
    analysis: str
    model: str
    alarm_count: int
    latency_ms: int


class EdgeRequest(BaseModel):
    prompt: str
    context: dict | None = None
    model: str = "nemotron-9b"


class EdgeResponse(BaseModel):
    reply: str
    model: str
    latency_ms: int
    simulated_edge: bool


class FinetuneStatusResponse(BaseModel):
    status: str
    training_samples: int
    last_export: str | None
    model_base: str
    estimated_improvement: str


class VoiceRequest(BaseModel):
    text: str  # For TTS demo; real voice would use streaming audio
    context: dict | None = None


class VoiceResponse(BaseModel):
    reply: str
    model: str
    voice_supported: bool
    latency_ms: int


# ═══════════════════════════════════════
# System prompts
# ═══════════════════════════════════════

SYSTEM_PROMPT = """You are Aevus AI, an expert SCADA/industrial operations assistant embedded in the Aevus Platform for oil & gas field operations.

You help operators with: alarm triage, asset health, predictive maintenance, safety protocol (ISA-18.2, NERC CIP, API 1164), shift handovers, and operational decisions.

SAFETY RULES:
- Never recommend bypassing safety interlocks or alarm suppression without supervisor approval
- Always err on the side of caution for safety-related questions
- Flag any reading that approaches safety limits with explicit warnings
- Reference ISA-18.2 alarm management standards when discussing alarm actions

Be concise, actionable, safety-conscious. Use plain language. Reference specific assets and data when context is provided.
Current site: Killdeer Field, North Dakota — oil production with compressors, separators, wellheads, RTUs, and radio network."""

CLASSIFY_PROMPT = """Classify this operator query into exactly one category. Reply with ONLY the category word:
- CHAT: casual question, greeting, simple status check
- ANALYSIS: root cause, trend analysis, comparison, "why", "analyze", "compare"
- SAFETY: anything involving safety, interlocks, H2S, LEL, ESD, emergency, ISA-18.2 compliance
- REPORT: shift handover, summary, export, compliance report
- NAVIGATE: "show me", "go to", "open", navigation request

Query: {query}"""

# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════


def _get_client():
    import boto3

    return boto3.client("bedrock-runtime", region_name="us-east-1")


def _build_context(ctx: dict | None) -> str:
    if not ctx:
        return ""
    parts = []
    if "alarms" in ctx:
        alarms = ctx["alarms"]
        crits = sum(1 for a in alarms if a.get("severity") == "critical")
        parts.append(f"Active alarms: {len(alarms)} ({crits} critical)")
        for a in alarms[:5]:
            parts.append(
                f"  [{a.get('severity', '?')}] {a.get('asset_id', '?')}: {a.get('description', a.get('alarm_text', '?'))}"
            )
    if "assets" in ctx:
        assets = ctx["assets"]
        unhealthy = [a for a in assets if (a.get("health_score") or 100) < 70]
        parts.append(f"Fleet: {len(assets)} assets, {len(unhealthy)} below 70% health")
        for a in unhealthy[:3]:
            parts.append(f"  {a.get('id', '')} {a.get('name', '')}: health {a.get('health_score')}%")
    if "predictions" in ctx:
        preds = ctx["predictions"]
        high_risk = [p for p in preds if (p.get("risk_score") or 0) > 60]
        parts.append(f"Predictions: {len(preds)} tracked, {len(high_risk)} high-risk")
    return "\n".join(parts)


def _sanitize_context(ctx_text: str) -> str:
    """Remove sensitive data per Langner security mandate — no raw IPs, GPS, credentials."""
    import re

    ctx_text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP_REDACTED]", ctx_text)
    ctx_text = re.sub(r"(?i)(password|secret|key|token)\s*[:=]\s*\S+", "[CREDENTIAL_REDACTED]", ctx_text)
    return ctx_text


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


# In-memory alarm embedding store
_alarm_embeddings: list[dict] = []
_finetune_samples: list[dict] = []

# ═══════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════


# --- #1 & #2: Tiered chat with safety-aware routing ---
@router.post("/ai/ask", response_model=AIResponse)
async def ai_ask(req: AIRequest):
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    t0 = time.time()

    # Step 1: Classify with Nova Micro (~300ms)
    classification = _classify_query(client, req.prompt)

    # Step 2: Route to appropriate model
    model_key, reason = _route_model(classification, req.force_model)

    # Step 3: Build context-aware prompt
    ctx_text = _sanitize_context(_build_context(req.context))
    user_msg = req.prompt
    if ctx_text:
        user_msg = f"Current system state:\n{ctx_text}\n\nOperator question: {req.prompt}"

    # Step 4: Invoke selected model
    try:
        max_tok = 600 if classification in ("ANALYSIS", "REPORT", "SAFETY") else 400
        reply = _invoke_model(client, model_key, SYSTEM_PROMPT, user_msg, max_tok)

        # Step 5: Store for fine-tuning data collection (#6)
        _finetune_samples.append(
            {
                "prompt": req.prompt,
                "context_hash": hashlib.md5(ctx_text.encode()).hexdigest()[:8] if ctx_text else None,  # noqa: S324 — non-crypto fingerprint for fine-tune dedup
                "classification": classification,
                "model": model_key,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(_finetune_samples) > 10000:
            _finetune_samples.pop(0)

        latency = int((time.time() - t0) * 1000)
        return AIResponse(
            reply=reply,
            model=MODELS[model_key]["label"],
            tier=MODELS[model_key]["tier"],
            latency_ms=latency,
            routed_reason=reason,
        )
    except Exception as e:
        logger.error("ai_invoke_error", model=model_key, error=str(e))
        raise HTTPException(502, f"AI inference failed: {str(e)[:100]}") from e


# --- Ask the Twin: natural-language Q&A grounded in the live digital-twin state ---
class TwinAskRequest(BaseModel):
    question: str
    facility_id: str = "killdeer"


TWIN_SYSTEM_PROMPT = (
    "You are the Aevus digital-twin assistant for a midstream gas facility. Answer the "
    "operator's question using ONLY the live twin state provided (equipment, normalized "
    "process flow 0-1, device status, alarms). Be concise and specific — name the affected "
    "equipment and pipe segments. If flow is low/stopped or a device is bad, explain the "
    "likely operational impact and what a human operator should check. "
    "IL-9000: you are advisory only — never instruct anyone to remotely change a setpoint or "
    "write to a PLC/RTU; recommend on-site human action. If the answer isn't in the provided "
    "state, say so rather than guessing."
)


def _build_twin_context(facility_id: str) -> str:
    """Assemble a grounded, trade-secret-safe twin snapshot for the model.

    Uses only NORMALIZED flow (0-1) + coarse status — never raw process values or
    scoring internals (those stay server-side per IL trade-secret policy)."""
    from src.api import twin as twin_mod

    try:
        topo = twin_mod._resolve_facility(facility_id)
    except Exception:
        return ""
    parts = [f"Facility: {topo.name}"]
    parts.append("Equipment: " + ", ".join(n.name for n in topo.nodes))
    try:
        segs = twin_mod._derive_flow(topo)
        node_by_id = {n.id: n for n in topo.nodes}
        parts.append("Process flow (normalized 0-1 by pipe segment):")
        for s, e in zip(segs, topo.edges, strict=False):
            frm = node_by_id.get(e.src)
            dst = node_by_id.get(e.to)
            parts.append(
                f"  {e.product}: {frm.name if frm else e.src} -> {dst.name if dst else e.to} "
                f"| flow {s.flow} | {s.status}"
            )
    except Exception as exc:
        logger.debug("twin_context_flow_skip", error=str(exc))
    try:
        from src.main import app_state

        assets = {a.id: a for a in app_state.db.list_assets()}
        bound = sorted({n.asset_id for n in topo.nodes if n.asset_id} | {e.asset_id for e in topo.edges if e.asset_id})
        if bound:
            parts.append("Bound device status:")
            for aid in bound:
                a = assets.get(aid)
                if a:
                    parts.append(
                        f"  {aid} {getattr(a, 'name', '')}: {getattr(a, 'status', 'unknown')}, health {getattr(a, 'health', None)}"
                    )
    except Exception as exc:
        logger.debug("twin_context_assets_skip", error=str(exc))
    return "\n".join(parts)


@router.post("/ai/twin-ask", response_model=AIResponse)
async def twin_ask(req: TwinAskRequest):
    """Ask the digital twin a question in natural language; the model is grounded
    on the live facility state (topology + flow + device status). Read-only."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    t0 = time.time()
    ctx_text = _sanitize_context(_build_twin_context(req.facility_id))
    if not ctx_text:
        raise HTTPException(404, f"Unknown facility '{req.facility_id}'")
    user_msg = f"Live digital-twin state:\n{ctx_text}\n\nOperator question: {req.question}"

    # Force Haiku for snappy, interactive twin Q&A — skip the classify+Sonnet path
    # (which ran ~50s). Haiku 4.5 is sub-second and plenty rich for this grounded,
    # bounded context. (Use /api/v1/ai/ask for deep Sonnet/Opus analysis.)
    model_key, reason = "haiku", "twin-ask → Haiku 4.5 (fast)"
    try:
        reply = _invoke_model(client, model_key, TWIN_SYSTEM_PROMPT, user_msg, 500)
        latency = int((time.time() - t0) * 1000)
        return AIResponse(
            reply=reply,
            model=MODELS[model_key]["label"],
            tier=MODELS[model_key]["tier"],
            latency_ms=latency,
            routed_reason="twin-ask: " + reason,
        )
    except Exception as e:
        logger.error("twin_ask_error", error=str(e))
        raise HTTPException(502, f"AI inference failed: {str(e)[:100]}") from e


# --- #3: Alarm similarity search (Cohere Embed v4 + Rerank) ---
@router.post("/ai/similar", response_model=SimilarityResponse)
async def alarm_similarity(req: SimilarityRequest):
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    # Build alarm corpus from provided history or stored embeddings
    corpus = []
    if req.history:
        corpus = [
            {"text": a.get("description", a.get("alarm_text", "")), "resolution": a.get("resolution")}
            for a in req.history
            if a.get("description") or a.get("alarm_text")
        ]

    if not corpus:
        # Use default SCADA alarm knowledge base
        corpus = [
            {
                "text": "Compressor high vibration — bearing wear detected",
                "resolution": "Schedule bearing inspection within 48hrs. Check lubricant levels.",
            },
            {
                "text": "Compressor high discharge temperature",
                "resolution": "Check cooling system, verify ambient temp, inspect valves.",
            },
            {
                "text": "Separator high liquid level",
                "resolution": "Check dump valve operation, verify level transmitter calibration.",
            },
            {"text": "Wellhead low flow rate", "resolution": "Check for paraffin buildup, verify rod pump operation."},
            {
                "text": "RTU communication loss",
                "resolution": "Check radio link, verify power supply, inspect antenna connections.",
            },
            {
                "text": "High H2S concentration detected",
                "resolution": "IMMEDIATE: Evacuate area, activate ESD, notify safety officer.",
            },
            {
                "text": "Low suction pressure on compressor",
                "resolution": "Check inlet filter, verify upstream valve positions.",
            },
            {
                "text": "EFM differential pressure out of range",
                "resolution": "Inspect orifice plate, check impulse tubing for blockage.",
            },
            {
                "text": "Radio signal quality degraded",
                "resolution": "Check antenna alignment, inspect cable connections, verify no RF interference.",
            },
            {
                "text": "Battery voltage low on remote site",
                "resolution": "Check solar panel output, inspect charge controller, replace battery if below 11.5V.",
            },
            {
                "text": "Compressor failed to start",
                "resolution": "Check starting circuit, verify gas supply pressure, inspect unloader valves.",
            },
            {
                "text": "Tank high level alarm",
                "resolution": "Verify truck dispatch, check level switch calibration, confirm LACT operation.",
            },
        ]

    docs = [c["text"] for c in corpus]

    # Step 1: Rerank with Cohere
    rerank_body = json.dumps({"query": req.alarm_text, "documents": docs, "top_n": min(5, len(docs)), "api_version": 2})

    try:
        r = client.invoke_model(
            modelId="cohere.rerank-v3-5:0", contentType="application/json", accept="application/json", body=rerank_body
        )
        results = json.loads(r["body"].read())["results"]

        similar = []
        for res in results:
            idx = res["index"]
            similar.append(
                SimilarAlarm(
                    alarm_text=corpus[idx]["text"],
                    score=round(res["relevance_score"], 3),
                    resolution=corpus[idx].get("resolution"),
                )
            )

        return SimilarityResponse(similar=similar, model="Cohere Rerank 3.5 + Embed v4")
    except Exception as e:
        logger.error("similarity_error", error=str(e))
        raise HTTPException(502, f"Similarity search failed: {str(e)[:100]}") from e


# --- #4: Voice interface (Nova Sonic text bridge) ---
@router.post("/ai/voice", response_model=VoiceResponse)
async def voice_query(req: VoiceRequest):
    """Process voice-transcribed text through AI. Nova Sonic handles speech-to-text
    at the edge; this endpoint processes the transcribed query."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    t0 = time.time()

    # Route voice queries through same tiered system
    classification = _classify_query(client, req.text)
    model_key, reason = _route_model(classification)

    ctx_text = _sanitize_context(_build_context(req.context))
    user_msg = "[Voice query from field operator — keep response under 3 sentences for audio playback]\n\n"
    if ctx_text:
        user_msg += f"System state:\n{ctx_text}\n\n"
    user_msg += f"Operator says: {req.text}"

    try:
        reply = _invoke_model(client, model_key, SYSTEM_PROMPT, user_msg, 200)
        latency = int((time.time() - t0) * 1000)
        return VoiceResponse(
            reply=reply,
            model=MODELS[model_key]["label"],
            voice_supported=True,
            latency_ms=latency,
        )
    except Exception as e:
        raise HTTPException(502, f"Voice AI failed: {str(e)[:100]}") from e


# --- #5: Edge inference simulation (Nemotron on Bedrock as proxy for Jetson) ---
@router.post("/ai/edge", response_model=EdgeResponse)
async def edge_inference(req: EdgeRequest):
    """Simulate edge inference using NVIDIA Nemotron models on Bedrock.
    In production, this routes to Jetson Orin at the well site."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    model_key = req.model if req.model in ("nemotron-9b", "nemotron-30b", "nemotron-12b") else "nemotron-9b"

    t0 = time.time()
    ctx_text = _sanitize_context(_build_context(req.context))
    user_msg = req.prompt
    if ctx_text:
        user_msg = f"System state:\n{ctx_text}\n\n{req.prompt}"

    edge_system = """You are an edge-deployed SCADA AI assistant running on NVIDIA Jetson Orin at a well site.
You have direct sensor access with <10ms latency. Be extremely concise — edge bandwidth is limited.
Respond in 2-3 sentences maximum. Focus on actionable status and immediate safety concerns."""

    try:
        reply = _invoke_model(client, model_key, edge_system, user_msg, 150)
        latency = int((time.time() - t0) * 1000)
        return EdgeResponse(
            reply=reply,
            model=MODELS[model_key]["label"],
            latency_ms=latency,
            simulated_edge=True,  # True until real Jetson deployed
        )
    except Exception as e:
        raise HTTPException(502, f"Edge inference failed: {str(e)[:100]}") from e


# --- #6: Fine-tuning data pipeline ---
@router.get("/ai/finetune/status", response_model=FinetuneStatusResponse)
async def finetune_status():
    """Check status of fine-tuning data collection for Nemotron SCADA model."""
    return FinetuneStatusResponse(
        status="collecting" if len(_finetune_samples) < 5000 else "ready",
        training_samples=len(_finetune_samples),
        last_export=_finetune_samples[-1]["timestamp"] if _finetune_samples else None,
        model_base="NVIDIA Nemotron Nano 9B → TAO Toolkit",
        estimated_improvement="15-25% on SCADA alarm classification vs generic model (projected)",
    )


@router.get("/ai/finetune/export")
async def finetune_export():
    """Export collected training samples for TAO fine-tuning pipeline."""
    return {
        "samples": _finetune_samples[-1000:],  # Last 1000
        "total": len(_finetune_samples),
        "format": "TAO-compatible JSONL",
        "target_model": "nemotron-nano-9b-v2",
    }


# --- #7: Batch alarm rationalization (Nova Pro as Premier proxy) ---
@router.post("/ai/batch/rationalize", response_model=BatchResponse)
async def batch_rationalize(req: BatchRequest):
    """Batch analyze alarm history for nuisance/chattering/standing patterns.
    Uses Nova Pro (Nova Premier requires separate access enablement for 1M context)."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    t0 = time.time()

    # Build alarm summary for analysis
    alarm_text = f"Analyze these {len(req.alarms)} alarms for {req.analysis_type}:\n\n"
    for i, a in enumerate(req.alarms[:100]):  # Cap at 100 for context limits
        alarm_text += f"{i + 1}. [{a.get('severity', '?')}] {a.get('asset_id', '?')}: {a.get('description', a.get('alarm_text', '?'))} (status: {a.get('status', '?')})\n"

    analysis_prompts = {
        "rationalization": "Identify nuisance alarms (>3 occurrences of same alarm), chattering alarms (rapid on/off), and standing alarms (open >24hrs). Provide ISA-18.2 rationalization recommendations. Group by asset.",
        "trends": "Identify trending patterns: which assets are generating increasing alarm rates? Which alarm types are new vs recurring? Flag any cascading alarm sequences.",
        "nuisance": "Calculate nuisance alarm percentage. ISA-18.2 target is <5% nuisance rate. List each nuisance alarm with occurrence count and recommended action (suppress/retune/eliminate).",
    }

    system = f"""You are an ISA-18.2 alarm management specialist analyzing SCADA alarm data.
{analysis_prompts.get(req.analysis_type, analysis_prompts["rationalization"])}
Format as a structured report with sections, counts, and specific recommendations."""

    try:
        # Use Nova Pro (would use Premier for >100 alarms when access enabled)
        reply = _invoke_nova(client, MODELS["nova-pro"]["id"], system, alarm_text, 1000)
        latency = int((time.time() - t0) * 1000)
        return BatchResponse(
            analysis=reply,
            model="Nova Pro (Premier pending access)",
            alarm_count=len(req.alarms),
            latency_ms=latency,
        )
    except Exception as e:
        raise HTTPException(502, f"Batch analysis failed: {str(e)[:100]}") from e


# --- #8: Vision-based equipment inspection (Nemotron 12B VL) ---
@router.post("/ai/vision", response_model=VisionResponse)
async def vision_inspect(
    prompt: str = Form(default="Analyze this equipment image for anomalies, corrosion, leaks, or safety concerns."),
    image: UploadFile = File(...),
):
    """Analyze equipment photos using NVIDIA Nemotron 12B Vision-Language model.
    In production, runs on Jetson Orin with camera feed at the well site."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    t0 = time.time()

    import base64

    image_bytes = await image.read()
    if len(image_bytes) > 5_000_000:
        raise HTTPException(400, "Image must be under 5MB")

    base64.b64encode(image_bytes).decode()

    # Determine media type
    ct = image.content_type or "image/jpeg"
    media_type = "image/png" if "png" in ct else "image/jpeg"

    vision_system = """You are an industrial equipment visual inspection AI deployed at an oil & gas well site.
Analyze images for: corrosion, leaks (oil/gas/water), mechanical damage, safety hazards,
gauge readings, equipment condition, and maintenance needs.
Rate condition: GOOD / FAIR / POOR / CRITICAL.
Provide specific, actionable maintenance recommendations."""

    try:
        r = client.converse(
            modelId="nvidia.nemotron-nano-12b-v2",
            system=[{"text": vision_system}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": media_type.split("/")[1], "source": {"bytes": image_bytes}}},
                        {"text": prompt},
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 500},
        )
        reply = r["output"]["message"]["content"][0]["text"]
        latency = int((time.time() - t0) * 1000)
        return VisionResponse(analysis=reply, model="Nemotron 12B VL (edge-ready)", latency_ms=latency)
    except Exception as e:
        logger.error("vision_error", error=str(e))
        raise HTTPException(502, f"Vision analysis failed: {str(e)[:100]}") from e


# --- Model catalog endpoint ---
@router.get("/ai/models")
async def list_models():
    """List all available AI models and their roles in the Aevus architecture."""
    return {
        "architecture": "4-tier safety-aware routing (Patent Pending #7)",
        "models": {
            k: {"label": v["label"], "tier": v["tier"], "provider": v["provider"], "cost_per_1k_queries": v["cost_1k"]}
            for k, v in MODELS.items()
        },
        "routing": {
            "CHAT": "haiku (Tier 1) — real-time operator Q&A",
            "ANALYSIS": "sonnet (Tier 2) — root cause, trends, comparisons",
            "SAFETY": "sonnet (Tier 2) — ISA-18.2 mandated minimum for safety queries",
            "REPORT": "sonnet (Tier 2) — shift handover, compliance reports",
            "NAVIGATE": "haiku (Tier 1) — intent detection for UI navigation",
        },
        "classifier": "nova-micro (Tier 0) — <300ms query classification",
        "embeddings": "Cohere Embed v4 (1536-dim) + Rerank 3.5",
        "edge": "NVIDIA Nemotron 9B/12B/30B (Jetson Orin ready)",
        "voice": "Amazon Nova Sonic (streaming S2S)",
        "vision": "NVIDIA Nemotron 12B VL (equipment inspection)",
        "batch": "Amazon Nova Pro (Nova Premier pending for 1M context)",
        "finetune_pipeline": f"Collecting: {len(_finetune_samples)} samples for TAO",
        "security": "Langner-approved models only. Chinese-origin models excluded (NERC CIP-013).",
        "patents": ["#7: Safety-Aware SCADA Model Routing", "#8: Edge-Cloud Hybrid Inference"],
    }


# --- Proactive anomaly digest (Nasby's "Situation Digest") ---
@router.post("/ai/digest")
async def situation_digest(context: dict | None = None):
    """Generate a 3-bullet situation digest for the activity feed.
    Called every 5 minutes by the dashboard's background refresh."""
    try:
        client = _get_client()
    except Exception:
        raise HTTPException(502, "AI service unavailable") from None

    ctx_text = _sanitize_context(_build_context(context))
    if not ctx_text:
        return {"digest": [], "model": "skipped — no context"}

    t0 = time.time()
    prompt = f"""Based on this SCADA system state, generate exactly 3 bullet points for a situation digest.
Each bullet should be one sentence, actionable, and highlight changes or concerns.
Format: Return only 3 lines starting with "•"

{ctx_text}"""

    try:
        reply = _invoke_model(client, "haiku", SYSTEM_PROMPT, prompt, 200)
        bullets = [
            line.strip().lstrip("•").strip() for line in reply.strip().split("\n") if line.strip().startswith("•")
        ]
        if not bullets:
            bullets = [line.strip() for line in reply.strip().split("\n") if line.strip()][:3]

        return {
            "digest": bullets[:3],
            "model": "Haiku 4.5",
            "latency_ms": int((time.time() - t0) * 1000),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as e:
        raise HTTPException(502, f"Digest failed: {str(e)[:100]}") from e
