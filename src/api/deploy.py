"""
Aevus Testbed --- Deploy Webhook
Triggers a deployment when called by GitHub Actions via webhook.
Protected by a separate deploy secret (not the API key).
"""

from __future__ import annotations

import asyncio
import subprocess

import structlog
from fastapi import APIRouter, Header, HTTPException

from src.config import settings

logger = structlog.get_logger()
router = APIRouter(prefix="/deploy", tags=["deploy"])


async def _run_deploy() -> str:
    """Run deploy script in background."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["/home/ubuntu/aevus-testbed/deploy/deploy.sh"],
            capture_output=True,
            text=True,
            # deploy.sh dispatches a DETACHED restart and returns fast, so this
            # is just a safety ceiling — but keep generous headroom over the dep
            # install so the subprocess is never killed before the restart is
            # dispatched (the 120s ceiling + a slow on-box step caused the
            # stale-code outage; see deploy/deploy.sh).
            timeout=300,
            cwd="/home/ubuntu/aevus-testbed",
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "Deploy timed out after 120s"


@router.post("/trigger")
async def trigger_deploy(
    x_deploy_secret: str = Header(..., alias="X-Deploy-Secret"),
) -> dict:
    """Trigger a deployment. Called by CI webhook."""
    if not settings.deploy_secret or x_deploy_secret != settings.deploy_secret:
        raise HTTPException(status_code=403, detail="Invalid deploy secret")

    logger.info("deploy_triggered", source="webhook")

    # Run deploy in background so we can return immediately
    asyncio.create_task(_run_deploy())

    return {"status": "deploy_started", "message": "Deployment triggered successfully"}
