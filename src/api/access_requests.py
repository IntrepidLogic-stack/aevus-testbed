"""
Aevus Testbed --- Access Request Management API
Enterprise access control: submit, review, approve/deny with Cognito integration.

Two request flows share POST /access-requests:

* ``flow="legacy"`` (default, unchanged behavior): store as ``pending`` and email an
  admin, who approves through the admin page (PUT /access-requests/{id}).
* ``flow="demo"`` (Door 1, behind ``DEMO_ACCESS_ENABLED``): short public form, then
  a business-vs-free-mail gate. Business domains are auto-provisioned into the
  synthetic-only ``DemoViewer`` group; free-mail is held as ``pending_review`` and
  approved by an admin via a signed one-time link (src/api/demo_access.py). Door 1
  only ever touches synthetic data and never grants any other group.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.auth import require_admin
from src.api.ratelimit import SlidingWindowRateLimiter
from src.config import settings
from src.integrations.hubspot import AccessEvent, push_access_event
from src.services import approve_link
from src.services.demo_provisioning import (
    ProvisioningError,
    get_cognito_client,
    normalize_phone,
    provision_demo_user,
    send_login_code,
)
from src.services.email_domains import InvalidEmailError, classify_email, email_domain, normalize_email

logger = structlog.get_logger()

router = APIRouter(tags=["access-requests"])

# AUTHORIZATION: every route below except the public POST /access-requests
# (the sign-up form) carries `dependencies=[Depends(require_admin)]`. The global
# APIKeyMiddleware only authenticates; it admits the shared master key and any
# pool user, so the admin check must live on each route. tests/test_admin_gate.py
# enforces this for every non-public route in this module.

# Admin page the notification email links to (the real approval UI).
ADMIN_PAGE_URL = "https://aevus.intrepidlogic.io/dashboard/admin.html"
# Public "Explore Demo" link in requester emails: the Comms console on its client-side
# SYNTHETIC dataset (?demo=true forces it; no /api/v1 call is made). The retired broad
# console is no longer served.
DEMO_CONSOLE_URL = "https://aevus.intrepidlogic.io/comms/Aevus_Comms_Console.html?demo=true"
# Page that reads the signed token from the URL fragment and POSTs it, with the
# admin's Cognito bearer, to /api/v1/demo-access/approve. A bare GET never approves.
APPROVE_PAGE_URL = "https://aevus.intrepidlogic.io/dashboard/approve.html"
LOGIN_URL = "https://aevus.intrepidlogic.io/login"

# ── Durable store ────────────────────────────────────────────────────────────
# Lives OUTSIDE the git working tree (see Settings.aevus_data_dir): deploy.sh runs
# `git reset --hard origin/main`, which reverts any tracked file in the repo.
DATA_FILE = Path(settings.aevus_data_dir) / "access_requests.json"
# Pre-fix location, read once for migration if DATA_FILE does not exist yet.
LEGACY_DATA_FILE = Path("/home/ubuntu/aevus-testbed/data/access_requests.json")

_STORE_LOCK = threading.RLock()


def ensure_data_dir() -> None:
    """Create the data dir and migrate the legacy in-tree store once. Never raises.

    Called from the app lifespan. If DATA_FILE is absent but the old in-tree file
    exists, copy it across (only ever when the new file does not exist, so a later
    `git reset --hard` reverting the old file can never overwrite live data).
    """
    try:
        with _STORE_LOCK:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not DATA_FILE.exists() and LEGACY_DATA_FILE.exists() and LEGACY_DATA_FILE != DATA_FILE:
                _save(json.loads(LEGACY_DATA_FILE.read_text()))
                logger.info("access_store_migrated", src=str(LEGACY_DATA_FILE), dst=str(DATA_FILE))
    except Exception as exc:  # noqa: BLE001 - startup must not fail on a store problem
        logger.error("access_store_init_failed", error=type(exc).__name__)


def _load() -> list[dict]:
    with _STORE_LOCK:
        if DATA_FILE.exists():
            return json.loads(DATA_FILE.read_text())
        if LEGACY_DATA_FILE.exists() and LEGACY_DATA_FILE != DATA_FILE:
            return json.loads(LEGACY_DATA_FILE.read_text())  # graceful one-time read before migration
        return []


def _save(reqs: list[dict]) -> None:
    """Atomic write (tmp + rename) so a crash mid-write cannot truncate the store."""
    with _STORE_LOCK:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_name(DATA_FILE.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(reqs, indent=2))
        os.replace(tmp, DATA_FILE)


def mutate(fn):
    """Run ``fn(reqs)`` under the store lock and persist; returns fn's result.

    Load-modify-save is one critical section, so concurrent requests cannot lose
    each other's writes and an id is never issued twice.
    """
    with _STORE_LOCK:
        reqs = _load()
        result = fn(reqs)
        _save(reqs)
        return result


def find_request(reqs: list[dict], req_id: str) -> dict | None:
    """Return the record with this id, or None."""
    return next((r for r in reqs if r.get("id") == req_id), None)


def public_view(rec: dict) -> dict:
    """Admin-visible record without server-side secrets."""
    return {k: v for k, v in rec.items() if k != "approve_nonce_sha256"}


# ── Abuse controls (in-app backstop; WAF/rate rules at the edge are separate) ──
ip_limiter = SlidingWindowRateLimiter(
    limit_attr="access_rl_ip_limit",
    window_attr="access_rl_window_seconds",
    detail="Too many requests. Please try again later.",
    log_event="access_request_ip_rate_limited",
)
email_limiter = SlidingWindowRateLimiter(
    limit_attr="access_rl_email_limit",
    window_attr="access_rl_window_seconds",
    detail="Too many requests for this address. Please try again later.",
    log_event="access_request_email_rate_limited",
)


def client_ip(request: Request) -> str:
    """Client IP for rate bucketing, from the hop our own proxy appended.

    The first X-Forwarded-For entry is client-controlled (spoofable), so take the
    Nth from the right (``access_trusted_proxy_hops``, default 1 = the entry our
    reverse proxy added). Falls back to the direct peer.
    """
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    hops = max(1, settings.access_trusted_proxy_hops)
    if xff and len(xff) >= hops:
        return xff[-hops]
    return request.client.host if request.client else "unknown"


def email_key(email: str) -> str:
    """Opaque limiter/log key for an address (avoids logging PII)."""
    return hashlib.sha256(email.encode()).hexdigest()[:16]


_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


class AccessRequest(BaseModel):
    """Public access-request payload (both flows). All strings are length-capped."""

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    company: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=32)
    # legacy flow: requested access level (viewer/operator); demo flow: job title.
    role: str = Field(default="viewer", max_length=80)
    reason: str = Field(default="", max_length=500)
    timestamp: str = Field(default="", max_length=64)  # ignored: the server stamps the time
    status: str = Field(default="pending", max_length=32)  # ignored: the server decides status
    flow: Literal["legacy", "demo"] = "legacy"
    delivery: Literal["email", "sms"] = "email"

    @field_validator("name", "company", "phone", "role", "reason", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> Any:
        """Reject control characters (header/log injection) and trim whitespace."""
        if isinstance(v, str):
            if _CTRL_RE.search(v):
                raise ValueError("control characters are not allowed")
            return v.strip()
        return v


class AccessDecision(BaseModel):
    status: str  # approved | denied
    cognito_create: bool = False
    decided_by: str = "admin"


# ── Email (SES, Aevus-branded). Every interpolated value is HTML-escaped. ──────

_ADMIN_FOOTER = """  <tr><td style="padding:16px 32px;background:rgba(0,0,0,0.2);border-top:1px solid rgba(148,163,184,0.06);">
    <table width="100%"><tr>
      <td><span style="font-size:10px;color:#4A5168;">Aevus by Intrepid Logic LLC</span></td>
      <td align="right"><span style="font-size:8px;color:#4A5168;letter-spacing:1.5px;">SDVOSB</span></td>
    </tr></table>
  </td></tr>"""


def _admin_email_html(rec: dict, *, headline: str, subtitle: str, button: str, url: str) -> str:
    """Branded admin notification. `url` is server-built; everything else is escaped."""
    e = html.escape
    name = rec.get("name") or "Unknown"
    tier = str(rec.get("role", "viewer")).upper()
    role_color = "#06B6D4" if tier in ("VIEWER", "DEMO") else "#FBBF24" if tier == "OPERATOR" else "#A78BFA"
    job = rec.get("job_role") or ""
    reason = rec.get("reason") or ("Job role: " + job if job else "No reason provided")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#070B16;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#070B16;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F172A;border:1px solid rgba(148,163,184,0.12);border-radius:16px;overflow:hidden;">
  <tr><td style="padding:28px 32px 20px;background:linear-gradient(135deg,rgba(6,182,212,0.08),transparent);border-bottom:1px solid rgba(148,163,184,0.08);">
    <table width="100%"><tr>
      <td><span style="font-size:22px;font-weight:700;letter-spacing:3px;color:#06B6D4;">AEVUS</span></td>
      <td align="right"><span style="font-size:10px;letter-spacing:1.5px;color:#64748B;text-transform:uppercase;">Demo Signup</span></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:24px 32px 16px;">
    <div style="font-size:16px;font-weight:600;color:#F1F5F9;margin-bottom:4px;">{e(headline)}</div>
    <div style="font-size:12px;color:#64748B;">{e(subtitle)}</div>
  </td></tr>
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" style="background:rgba(6,182,212,0.04);border:1px solid rgba(6,182,212,0.12);border-radius:12px;" cellpadding="16" cellspacing="0">
    <tr><td>
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td width="44" valign="top">
          <div style="width:40px;height:40px;border-radius:10px;background:rgba(6,182,212,0.12);color:#06B6D4;font-size:16px;font-weight:700;text-align:center;line-height:40px;">{e(name[:1].upper())}</div>
        </td>
        <td style="padding-left:12px;">
          <div style="font-size:15px;font-weight:600;color:#F1F5F9;">{e(name)}</div>
          <div style="font-size:12px;color:#94A3B8;margin-top:2px;">{e(rec.get("email", ""))}</div>
        </td>
        <td align="right" valign="top">
          <span style="display:inline-block;padding:3px 10px;border-radius:6px;font-size:10px;font-weight:700;letter-spacing:0.5px;color:{role_color};background:{role_color}18;border:1px solid {role_color}30;">{e(tier)}</span>
        </td>
      </tr></table>
    </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="50%" style="padding:8px 0;border-bottom:1px solid rgba(148,163,184,0.06);">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Company</div>
          <div style="font-size:13px;color:#F1F5F9;font-weight:500;">{e(rec.get("company") or "-")}</div>
        </td>
        <td width="50%" style="padding:8px 0 8px 16px;border-bottom:1px solid rgba(148,163,184,0.06);">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Phone</div>
          <div style="font-size:13px;color:#F1F5F9;font-weight:500;">{e(rec.get("phone") or "-")}</div>
        </td>
      </tr>
      <tr>
        <td colspan="2" style="padding:8px 0;">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Reason for Access</div>
          <div style="font-size:13px;color:#94A3B8;line-height:1.5;">{e(reason)}</div>
        </td>
      </tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 32px 24px;" align="center">
    <a href="{e(url, quote=True)}" style="display:inline-block;padding:12px 32px;background:#06B6D4;color:#070B16;font-size:13px;font-weight:700;text-decoration:none;border-radius:8px;letter-spacing:0.5px;">{e(button)}</a>
  </td></tr>
  <tr><td style="padding:0 32px 12px;">
    <div style="font-size:10px;color:#4A5168;text-align:center;font-family:monospace;">{e(rec.get("timestamp", ""))}</div>
  </td></tr>
{_ADMIN_FOOTER}
</table>
</td></tr></table>
</body></html>"""


def _requester_email_html(rec: dict, body: str, button: str, url: str) -> str:
    e = html.escape
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#070B16;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#070B16;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F172A;border:1px solid rgba(148,163,184,0.12);border-radius:16px;overflow:hidden;">
  <tr><td style="padding:28px 32px 20px;background:linear-gradient(135deg,rgba(6,182,212,0.08),transparent);border-bottom:1px solid rgba(148,163,184,0.08);">
    <span style="font-size:22px;font-weight:700;letter-spacing:3px;color:#06B6D4;">AEVUS</span>
  </td></tr>
  <tr><td style="padding:24px 32px 16px;">
    <div style="font-size:16px;font-weight:600;color:#F1F5F9;margin-bottom:8px;">Hi {e(rec.get("name", ""))},</div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">{e(body)}</div>
  </td></tr>
  <tr><td style="padding:0 32px 24px;" align="center">
    <a href="{e(url, quote=True)}" style="display:inline-block;padding:12px 32px;background:#06B6D4;color:#070B16;font-size:13px;font-weight:700;text-decoration:none;border-radius:8px;letter-spacing:0.5px;">{e(button)}</a>
  </td></tr>
{_ADMIN_FOOTER}
</table>
</td></tr></table>
</body></html>"""


def _ses_send(sender: str, to: list[str], subject: str, html_body: str, text_body: str) -> None:
    """Send one SES email. Raises on failure; callers log and continue."""
    import boto3

    boto3.client("sesv2", region_name="us-east-1").send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": to},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            }
        },
    )


def _notify_recipients() -> list[str]:
    return [a.strip() for a in settings.access_notify_to.split(",") if a.strip()]


def send_admin_notification(
    rec: dict, *, headline: str, subtitle: str, button: str, url: str, subject_prefix: str = "AEVUS Demo Signup"
) -> None:
    """Email the admin(s). Best effort: failures are logged, never raised."""
    try:
        name = rec.get("name", "Unknown")
        _ses_send(
            "Aevus Notifications <info@intrepidlogic.io>",
            _notify_recipients(),
            f"{subject_prefix}: {name} - {rec.get('company') or rec.get('email', '')}",
            _admin_email_html(rec, headline=headline, subtitle=subtitle, button=button, url=url),
            f"{headline}: {name} ({rec.get('email', '')}) at {rec.get('company') or '-'}. "
            f"Tier: {rec.get('role', '')}. Review: {url}",
        )
        logger.info("ses_notification_sent", request_id=rec.get("id"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ses_notification_failed", error=type(exc).__name__)


def send_requester_email(rec: dict, *, subject: str, body: str, button: str, url: str) -> None:
    """Email the requester. Best effort: failures are logged, never raised."""
    try:
        _ses_send(
            "Aevus Platform <info@intrepidlogic.io>",
            [rec["email"]],
            subject,
            _requester_email_html(rec, body, button, url),
            f"Hi {rec.get('name', '')}, {body} {url}",
        )
        logger.info("requester_email_sent", request_id=rec.get("id"), subject=subject)
    except Exception as exc:  # noqa: BLE001
        logger.warning("requester_email_failed", error=type(exc).__name__)


def hubspot_event(rec: dict, event: str, detail: str = "") -> AccessEvent:
    """Build the HubSpot event for a record (free-mail never maps to a Company)."""
    return AccessEvent(
        event=event,
        request_id=rec.get("id", ""),
        email=rec["email"],
        name=rec.get("name", ""),
        company=rec.get("company", ""),
        phone=rec.get("phone", ""),
        job_title=rec.get("job_role", ""),
        domain_class=rec.get("domain_class", "business"),
        detail=detail,
    )


# ── Provisioning shared by auto-provision, approve, and admin retry ───────────


def _provision_sync(rec: dict) -> tuple[str, str]:
    """Create the DemoViewer identity. Returns (status, cognito_username)."""
    result = provision_demo_user(
        get_cognito_client(),
        email=rec["email"],
        name=rec.get("name", ""),
        phone=rec.get("phone", ""),
        sms_enabled=settings.demo_sms_otp_enabled,
    )
    return ("provisioned" if result.usable_for_demo else "existing_account"), result.username


async def provision_record(req_id: str) -> str:
    """Provision the record's Cognito identity and persist the outcome.

    Returns the resulting status. Raises ProvisioningError on failure (the record
    is marked ``provision_failed`` with the error class, never the user-visible text).
    """
    rec = mutate(lambda reqs: dict(find_request(reqs, req_id) or {}))
    if not rec:
        raise ProvisioningError("request not found")
    try:
        status, username = await asyncio.to_thread(_provision_sync, rec)
    except ProvisioningError as exc:
        err = str(exc)
        mutate(lambda reqs: (find_request(reqs, req_id) or {}).update(status="provision_failed", provision_error=err))
        logger.error("demo_provision_failed", request_id=req_id, error=err)
        raise

    def _ok(reqs: list[dict]) -> None:
        r = find_request(reqs, req_id)
        if r is not None:
            r.update(status=status, cognito_username=username, provisioned_at=datetime.now(UTC).isoformat())
            r.pop("provision_error", None)

    mutate(_ok)
    return status


async def request_login_code(email: str, delivery: str) -> Any:
    """Ask Cognito to deliver a one-time code (SMS only if enabled). Raises ProvisioningError."""
    if delivery == "sms" and not settings.demo_sms_otp_enabled:
        delivery = "email"
    return await asyncio.to_thread(
        send_login_code, get_cognito_client(), client_id=settings.demo_cognito_client_id, email=email, delivery=delivery
    )


def _domain_cap_reached(reqs: list[dict], domain: str) -> bool:
    """True if this business domain already auto-provisioned its daily quota."""
    cap = settings.demo_domain_daily_cap
    if cap <= 0:
        return False
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    n = sum(
        1
        for r in reqs
        if r.get("flow") == "demo"
        and r.get("domain") == domain
        and r.get("status") == "provisioned"
        and r.get("timestamp", "") >= since
    )
    return n >= cap


def _new_record(req: AccessRequest, email: str, phone: str) -> dict:
    return {
        "name": req.name,
        "email": email,
        "company": req.company,
        "phone": phone,
        "role": req.role if req.flow == "legacy" else "demo",
        "job_role": req.role if req.flow == "demo" else "",
        "reason": req.reason,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "pending",
        "flow": req.flow,
        "domain": email_domain(email),
        "domain_class": classify_email(email),
    }


@router.post("/access-requests")
async def submit_access_request(req: AccessRequest, request: Request, background: BackgroundTasks):
    """Public sign-up. Rate limited per IP and per address; payload validated."""
    ip = client_ip(request)
    ip_limiter.check(ip)
    try:
        email = normalize_email(req.email)
    except InvalidEmailError:
        raise HTTPException(status_code=422, detail="A valid email address is required") from None
    email_limiter.check(email_key(email))

    phone = req.phone
    if req.flow == "demo":
        if not req.company:
            raise HTTPException(status_code=422, detail="Company is required")
        try:
            phone = normalize_phone(req.phone)
        except ValueError:
            raise HTTPException(status_code=422, detail="A valid phone number is required") from None

    rec = _new_record(req, email, phone)

    def _insert(reqs: list[dict]) -> dict:
        rec["id"] = str(len(reqs) + 1).zfill(4)
        if req.flow == "demo":
            demo_on = settings.demo_access_enabled
            if rec["domain_class"] == "business" and demo_on and not _domain_cap_reached(reqs, rec["domain"]):
                rec["status"] = "provisioning"
            else:
                rec["status"] = "pending_review"
                if rec["domain_class"] == "business" and demo_on:
                    rec["review_reason"] = "domain_daily_cap"
        reqs.append(rec)
        return dict(rec)

    saved = mutate(_insert)
    logger.info(
        "access_request_submitted",
        request_id=saved["id"],
        flow=saved["flow"],
        domain_class=saved["domain_class"],
        status=saved["status"],
        ip=ip,
        email_key=email_key(email),
    )
    background.add_task(push_access_event, hubspot_event(saved, "requested"))

    # ── Legacy flow: unchanged semantics, fixed link ──
    if saved["flow"] == "legacy":
        background.add_task(
            send_admin_notification,
            saved,
            headline="New Access Request",
            subtitle="Someone wants to access the Aevus Console",
            button="Review & Approve",
            url=ADMIN_PAGE_URL,
        )
        background.add_task(
            send_requester_email,
            saved,
            subject="Aevus Access Request Received",
            body=(
                "Thank you for requesting access to the Aevus SCADA Intelligence Platform. "
                "An administrator will review your request shortly. In the meantime, explore the demo."
            ),
            button="Explore Demo",
            url=DEMO_CONSOLE_URL,
        )
        return {"status": "ok", "id": saved["id"]}

    # ── Door 1: business domain -> auto-provision DemoViewer ──
    if saved["status"] == "provisioning":
        try:
            outcome = await provision_record(saved["id"])
        except ProvisioningError:
            background.add_task(
                send_admin_notification,
                saved,
                headline="Demo provisioning FAILED",
                subtitle="Business domain, auto-provision error. Needs a look.",
                button="Open admin",
                url=ADMIN_PAGE_URL,
            )
            return {"status": "received", "id": saved["id"]}
        background.add_task(
            push_access_event, hubspot_event(saved, "provisioned", "Auto-provisioned (business domain)")
        )
        background.add_task(
            send_admin_notification,
            saved,
            headline="Demo access auto-provisioned",
            subtitle="Business domain. Synthetic-only DemoViewer. FYI, no action needed.",
            button="Open admin",
            url=ADMIN_PAGE_URL,
        )
        if outcome != "provisioned":
            return {"status": "received", "id": saved["id"]}  # existing real account: untouched, no code sent
        try:
            code = await request_login_code(email, req.delivery)
        except ProvisioningError as exc:
            logger.error("demo_code_send_failed", request_id=saved["id"], error=str(exc))
            return {"status": "received", "id": saved["id"]}
        return {"status": "code_sent", "id": saved["id"], "challenge": code.challenge, "session": code.session}

    # ── Door 1: free-mail (or capped) -> hold for a human, signed one-time link ──
    approve_url = ADMIN_PAGE_URL
    if settings.demo_access_enabled:
        try:
            token, nonce_hash = approve_link.issue_token(
                saved["id"], settings.access_approve_signing_key, settings.access_approve_ttl_seconds
            )
            exp = (datetime.now(UTC) + timedelta(seconds=settings.access_approve_ttl_seconds)).isoformat()
            mutate(
                lambda reqs: (find_request(reqs, saved["id"]) or {}).update(
                    approve_nonce_sha256=nonce_hash, approve_expires_at=exp
                )
            )
            approve_url = f"{APPROVE_PAGE_URL}#t={token}"  # fragment: never sent to servers or logs
        except approve_link.ApproveKeyMissingError:
            logger.error("approve_link_unavailable", reason="signing_key_not_configured", request_id=saved["id"])
    background.add_task(
        send_admin_notification,
        saved,
        headline="Demo Access: Approval Needed",
        subtitle="Free-mail or capped domain. Held for review; one-click link is single-use and expires.",
        button="Approve Demo Access" if approve_url != ADMIN_PAGE_URL else "Review in Admin",
        url=approve_url,
        subject_prefix="AEVUS Demo APPROVAL",
    )
    background.add_task(
        send_requester_email,
        saved,
        subject="Aevus Demo Request Received",
        body="Thanks for your interest in Aevus. We are reviewing your request and will follow up shortly.",
        button="Explore Demo",
        url=DEMO_CONSOLE_URL,
    )
    return {"status": "pending_review", "id": saved["id"]}


@router.get("/access-requests", dependencies=[Depends(require_admin)])
async def list_access_requests():
    return [public_view(r) for r in _load()]


@router.put("/access-requests/{req_id}", dependencies=[Depends(require_admin)])
async def update_access_request(req_id: str, decision: AccessDecision):
    reqs = _load()
    target = find_request(reqs, req_id)

    if not target:
        return {"status": "error", "message": "Request not found"}

    if target.get("flow") == "demo":
        # Door 1 records are provisioned only through the DemoViewer path. The
        # legacy branch below creates a temp-password user in a role group.
        if decision.cognito_create:
            return {"status": "error", "message": "Demo requests are provisioned via /demo-access/approve"}
        target.pop("approve_nonce_sha256", None)  # any manual decision voids the emailed link

    target["status"] = decision.status
    target["decided_at"] = datetime.now(UTC).isoformat()
    target["decided_by"] = decision.decided_by

    # Approve → create Cognito user
    if decision.status == "approved" and decision.cognito_create:
        try:
            import boto3

            cognito = boto3.client("cognito-idp", region_name="us-east-1")
            cognito.admin_create_user(
                UserPoolId="us-east-1_CVFBcLJV3",
                Username=target["email"],
                UserAttributes=[
                    {"Name": "email", "Value": target["email"]},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": target.get("name", "")},
                ],
                DesiredDeliveryMediums=["EMAIL"],
                ForceAliasCreation=False,
            )
            # Add to role group
            role_group = target.get("role", "viewer").capitalize()
            try:
                cognito.admin_add_user_to_group(
                    UserPoolId="us-east-1_CVFBcLJV3",
                    Username=target["email"],
                    GroupName=role_group,
                )
            except Exception:
                pass  # Group may not exist yet

            target["cognito_created"] = True
            logger.info("cognito_user_created", email=target["email"], role=role_group)
        except Exception as e:
            target["cognito_error"] = str(e)
            logger.error("cognito_create_failed", email=target["email"], error=str(e))

    _save(reqs)
    logger.info("access_request_decided", id=req_id, status=decision.status)
    return {"status": "ok"}


# ── User Management (Cognito) ─────────────────────────────


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users():
    """List all Cognito users with their groups."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    result = cognito.list_users(UserPoolId=pool)
    users = []
    for u in result.get("Users", []):
        attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
        groups = cognito.admin_list_groups_for_user(UserPoolId=pool, Username=u["Username"])
        gs = [g["GroupName"] for g in groups.get("Groups", [])]
        users.append(
            {
                "username": u["Username"],
                "email": attrs.get("email", ""),
                "name": attrs.get("name", ""),
                "status": u["UserStatus"],
                "enabled": u["Enabled"],
                "created": u["UserCreateDate"].isoformat(),
                "modified": u.get("UserLastModifiedDate", u["UserCreateDate"]).isoformat(),
                "groups": gs,
            }
        )
    return users


@router.put("/users/{username}/role", dependencies=[Depends(require_admin)])
async def change_user_role(username: str, body: dict):
    """Change a user's group (role)."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    new_role = body.get("role", "Viewer")

    # Remove from all current groups
    current = cognito.admin_list_groups_for_user(UserPoolId=pool, Username=username)
    for g in current.get("Groups", []):
        cognito.admin_remove_user_from_group(UserPoolId=pool, Username=username, GroupName=g["GroupName"])

    # Add to new group
    cognito.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=new_role)
    logger.info("user_role_changed", username=username, role=new_role)
    return {"status": "ok", "role": new_role}


@router.put("/users/{username}/toggle", dependencies=[Depends(require_admin)])
async def toggle_user(username: str):
    """Enable or disable a user."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"

    user = cognito.admin_get_user(UserPoolId=pool, Username=username)
    if user["Enabled"]:
        cognito.admin_disable_user(UserPoolId=pool, Username=username)
        logger.info("user_disabled", username=username)
        return {"status": "ok", "enabled": False}
    else:
        cognito.admin_enable_user(UserPoolId=pool, Username=username)
        logger.info("user_enabled", username=username)
        return {"status": "ok", "enabled": True}


@router.delete("/users/{username}", dependencies=[Depends(require_admin)])
async def delete_user(username: str):
    """Permanently delete a Cognito user."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    cognito.admin_delete_user(UserPoolId=pool, Username=username)
    logger.info("user_deleted", username=username)
    return {"status": "ok"}


@router.post("/users/{username}/reset-password", dependencies=[Depends(require_admin)])
async def reset_user_password(username: str):
    """Force a password reset — sends new temp password via email."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    cognito.admin_reset_user_password(UserPoolId=pool, Username=username)
    logger.info("user_password_reset", username=username)
    return {"status": "ok"}


@router.post("/users/{username}/mfa", dependencies=[Depends(require_admin)])
async def enable_mfa(username: str):
    """Enable TOTP MFA for a user."""
    import boto3

    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    try:
        cognito.admin_set_user_mfa_preference(
            UserPoolId=pool, Username=username, SoftwareTokenMfaSettings={"Enabled": True, "PreferredMfa": True}
        )
        logger.info("mfa_enabled", username=username)
        return {"status": "ok"}
    except Exception as e:
        logger.warning("mfa_enable_failed", username=username, error=str(e))
        return {"status": "error", "error": str(e)}
