"""
Aevus Testbed --- Integrations API Routes
Manage external system integrations (SCADA historians, cloud platforms, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/integrations", tags=["integrations"])

# Integration registry — will be populated from config/database
_INTEGRATIONS = [
    {
        "id": "influxdb",
        "name": "InfluxDB",
        "type": "time_series_db",
        "status": "active",
        "description": "Primary telemetry storage",
    },
    {
        "id": "aws-bedrock",
        "name": "AWS Bedrock",
        "type": "ai_inference",
        "status": "configured",
        "description": "AI/ML prediction engine",
    },
]


@router.get("")
async def list_integrations() -> dict:
    """List all configured integrations and their status."""
    return {
        "integrations": _INTEGRATIONS,
        "total": len(_INTEGRATIONS),
    }


@router.get("/{integration_id}")
async def get_integration(integration_id: str) -> dict:
    """Get details for a specific integration."""
    for integ in _INTEGRATIONS:
        if integ["id"] == integration_id:
            return integ
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Integration {integration_id} not found")
