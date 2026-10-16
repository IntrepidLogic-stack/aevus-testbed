"""
Aevus -- Door 1 demo access: approve link, code delivery, session probe.

Account/provisioning routes only. Nothing here reads or writes telemetry, and no
route can reach field equipment (IL-9000 posture unchanged). The only group ever
granted is ``DemoViewer`` (see src/services/demo_provisioning.py), which the API
confines to the synthetic data source (see src/api/auth.py).

Routes (mounted under /api/v1):

* POST /demo-access/approve            admin only (require_admin). Consumes the signed
                                       one-time token from the free-mail email, then
                                       provisions the DemoViewer identity.
* POST /demo-access/requests/{id}/provision
                                       admin only. Retry provisioning for a record that
                                       is ``approved`` or ``provision_failed``.
* POST /demo-access/code               PUBLIC, rate limited. Sends a one-time sign-in
                                       code to an already-provisioned demo user. The
                                       reply has the same shape whether or not the
                                       address is eligible (no account enumeration).
* GET  /demo-access/session            any valid bearer. Tells the console which data
                                       source the identity may use; marks first login.

The approve token authorizes nothing by itself: it only names the pending request.
The caller must also be a verified Cognito Admin.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api import access_requests as store
from src.api.auth import bearer_claims, is_demo_identity, require_admin
from src.api.ratelimit import SlidingWindowRateLimiter
from src.config import settings
from src.integrations.hubspot import push_access_event
from src.services import approve_link
from src.services.demo_provisioning import ProvisioningError
from src.services.email_domains import InvalidEmailError, normalize_email

logger = structlog.get_logger()

router = APIRouter(prefix="/demo-access", tags=["demo-access"])

# Separate bucket from the sign-up form: a legitimate user may need a few codes.
code_limiter = SlidingWindowRateLimiter(
    limit_attr="access_rl_email_limit",
    window_attr="access_rl_window_seconds",
    detail="Too many code requests. Please try again later.",
    log_event="demo_code_rate_limited",
)

_NOT_ENABLED = "Demo access is not enabled"


class ApproveBody(BaseModel):
    """Signed one-time token taken from the approval email's URL fragment."""

    token: str = Field(min_length=20, max_length=1024)


class CodeBody(BaseModel):
    """Public request for a sign-in code."""

    email: str = Field(min_length=3, max_length=254)
    delivery: str = Field(default="email", pattern="^(email|sms)$")


def _approver(claims: dict[str, Any]) -> str:
    return str(claims.get("email") or claims.get("cognito:username") or claims.get("username") or "admin")


@router.post("/approve")
async def approve(body: ApproveBody, background: BackgroundTasks, claims: dict = Depends(require_admin)):
    """Consume a signed approve token (single use) and provision the DemoViewer user."""
    if not settings.demo_access_enabled:
        raise HTTPException(status_code=503, detail=_NOT_ENABLED)
    try:
        c = approve_link.verify_token(body.token, settings.access_approve_signing_key)
    except approve_link.ApproveKeyMissingError:
        raise HTTPException(status_code=503, detail="Approve links are not configured") from None
    except approve_link.ApproveTokenExpiredError:
        raise HTTPException(status_code=410, detail="This approve link has expired") from None
    except approve_link.ApproveTokenError:
        raise HTTPException(status_code=400, detail="Invalid approve link") from None

    who = _approver(claims)
    now = datetime.now(UTC).isoformat()

    def _consume(reqs: list[dict]) -> dict | None:
        r = store.find_request(reqs, c.request_id)
        stored = (r or {}).get("approve_nonce_sha256")
        if (
            not r
            or r.get("flow") != "demo"
            or r.get("status") != "pending_review"
            or not stored
            or not hmac.compare_digest(stored, approve_link.hash_nonce(c.nonce))
        ):
            return None
        # Single use: the hash is removed in the same critical section that approves.
        r.pop("approve_nonce_sha256", None)
        r.update(status="approved", approved_at=now, approved_by=who, approve_used_at=now)
        return dict(r)

    rec = store.mutate(_consume)
    if rec is None:
        logger.warning("demo_approve_rejected", request_id=c.request_id, reason="used_or_not_pending")
        raise HTTPException(status_code=409, detail="This request was already handled or is no longer pending")
    logger.info("demo_access_approved", request_id=rec["id"], approved_by=who)
    background.add_task(push_access_event, store.hubspot_event(rec, "approved", f"Approved by {who}"))
    return await _provision_and_announce(rec, background)


@router.post("/requests/{req_id}/provision", dependencies=[Depends(require_admin)])
async def retry_provision(req_id: str, background: BackgroundTasks):
    """Admin retry for an approved record whose provisioning failed (or was approved by hand)."""
    if not settings.demo_access_enabled:
        raise HTTPException(status_code=503, detail=_NOT_ENABLED)
    rec = store.mutate(lambda reqs: dict(store.find_request(reqs, req_id) or {}))
    if not rec or rec.get("flow") != "demo" or rec.get("status") not in ("approved", "provision_failed"):
        raise HTTPException(status_code=409, detail="Request is not awaiting provisioning")
    return await _provision_and_announce(rec, background)


async def _provision_and_announce(rec: dict, background: BackgroundTasks) -> dict:
    try:
        status = await store.provision_record(rec["id"])
    except ProvisioningError:
        raise HTTPException(
            status_code=502, detail="Approved, but provisioning failed. Retry from the admin page."
        ) from None
    if status == "provisioned":
        background.add_task(push_access_event, store.hubspot_event(rec, "provisioned", "DemoViewer created"))
        background.add_task(
            store.send_requester_email,
            rec,
            subject="Your Aevus demo access is ready",
            body=(
                "You are approved for the Aevus demo. Choose 'email me a code' on the sign-in page "
                "and enter the code we send you. There is no password to create."
            ),
            button="Sign in to the demo",
            url=store.LOGIN_URL,
        )
    return {"status": status, "id": rec["id"]}


def _decoy() -> dict:
    """Same-shape reply for ineligible addresses, so the route is not an account oracle."""
    return {"status": "sent", "challenge": "EMAIL_OTP", "session": secrets.token_urlsafe(600)}


@router.post("/code")
async def request_code(body: CodeBody, request: Request):
    """PUBLIC: send a one-time sign-in code to a provisioned demo user."""
    store.ip_limiter.check(store.client_ip(request))
    try:
        email = normalize_email(body.email)
    except InvalidEmailError:
        raise HTTPException(status_code=422, detail="A valid email address is required") from None
    code_limiter.check(store.email_key(email))

    if not settings.demo_access_enabled:
        return _decoy()
    eligible = any(
        r.get("flow") == "demo" and r.get("email") == email and r.get("status") == "provisioned" for r in store._load()
    )
    if not eligible:
        return _decoy()
    try:
        code = await store.request_login_code(email, body.delivery)
    except ProvisioningError as exc:
        logger.error("demo_code_send_failed", email_key=store.email_key(email), error=str(exc))
        return _decoy()
    return {"status": "sent", "challenge": code.challenge, "session": code.session}


@router.get("/session")
async def session(request: Request, background: BackgroundTasks):
    """Tell the console which data source this identity may use; mark first login.

    A DemoViewer identity is synthetic-only: the live API denies it outright, so
    ``live_allowed`` is False and the console must stay on the synthetic source.
    """
    claims = bearer_claims(request)
    if claims is None:
        raise HTTPException(status_code=401, detail="Valid bearer token required")
    demo = is_demo_identity(claims)
    if demo:
        email = str(claims.get("email", "")).lower()
        ids = {str(claims[k]) for k in ("cognito:username", "username", "sub") if claims.get(k)}
        now = datetime.now(UTC).isoformat()

        def _mark(reqs: list[dict]) -> dict | None:
            for r in reqs:
                if (
                    r.get("flow") == "demo"
                    and r.get("status") == "provisioned"
                    and not r.get("first_login_at")
                    and ((email and r.get("email") == email) or r.get("cognito_username") in ids)
                ):
                    r["first_login_at"] = now
                    return dict(r)
            return None

        first = store.mutate(_mark)
        if first:
            background.add_task(push_access_event, store.hubspot_event(first, "first_login"))
    return {
        "identity": "demo" if demo else "standard",
        "data_source": "synthetic" if demo else None,
        "live_allowed": not demo,
    }
