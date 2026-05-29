"""
Aevus Testbed --- Access Request Management API
Enterprise access control: submit, review, approve/deny with Cognito integration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(tags=["access-requests"])

DATA_FILE = Path("/home/ubuntu/aevus-testbed/data/access_requests.json")

class AccessRequest(BaseModel):
    name: str
    email: str
    company: str = ""
    phone: str = ""
    role: str = "viewer"
    reason: str = ""
    timestamp: str = ""
    status: str = "pending"

class AccessDecision(BaseModel):
    status: str  # approved | denied
    cognito_create: bool = False
    decided_by: str = "admin"


def _load() -> list[dict]:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return []

def _save(reqs: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(reqs, indent=2))


@router.post("/access-requests")
async def submit_access_request(req: AccessRequest):
    reqs = _load()
    data = req.model_dump()
    data["id"] = str(len(reqs) + 1).zfill(4)
    data["status"] = "pending"
    if not data.get("timestamp"):
        data["timestamp"] = datetime.now(UTC).isoformat()
    reqs.append(data)
    _save(reqs)
    logger.info("access_request_submitted", email=data["email"], company=data.get("company"))

    # Email notification via SES — Aevus-branded HTML
    try:
        import boto3
        ses = boto3.client("sesv2", region_name="us-east-1")
        name = data.get("name", "Unknown")
        email = data.get("email", "—")
        company = data.get("company", "—")
        phone = data.get("phone", "—")
        role = data.get("role", "viewer").upper()
        reason = data.get("reason", "No reason provided")
        ts = data.get("timestamp", "—")

        role_color = "#06B6D4" if role == "VIEWER" else "#FBBF24" if role == "OPERATOR" else "#A78BFA"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#070B16;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#070B16;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F172A;border:1px solid rgba(148,163,184,0.12);border-radius:16px;overflow:hidden;">

  <!-- Header -->
  <tr><td style="padding:28px 32px 20px;background:linear-gradient(135deg,rgba(6,182,212,0.08),transparent);border-bottom:1px solid rgba(148,163,184,0.08);">
    <table width="100%"><tr>
      <td><span style="font-size:22px;font-weight:700;letter-spacing:3px;color:#06B6D4;">AEVUS</span></td>
      <td align="right"><span style="font-size:10px;letter-spacing:1.5px;color:#64748B;text-transform:uppercase;">Demo Signup</span></td>
    </tr></table>
  </td></tr>

  <!-- Title -->
  <tr><td style="padding:24px 32px 16px;">
    <div style="font-size:16px;font-weight:600;color:#F1F5F9;margin-bottom:4px;">New Access Request</div>
    <div style="font-size:12px;color:#64748B;">Someone wants to access the Aevus Console</div>
  </td></tr>

  <!-- User Card -->
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" style="background:rgba(6,182,212,0.04);border:1px solid rgba(6,182,212,0.12);border-radius:12px;" cellpadding="16" cellspacing="0">
    <tr><td>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="44" valign="top">
            <div style="width:40px;height:40px;border-radius:10px;background:rgba(6,182,212,0.12);color:#06B6D4;font-size:16px;font-weight:700;text-align:center;line-height:40px;">{name[0].upper()}</div>
          </td>
          <td style="padding-left:12px;">
            <div style="font-size:15px;font-weight:600;color:#F1F5F9;">{name}</div>
            <div style="font-size:12px;color:#94A3B8;margin-top:2px;">{email}</div>
          </td>
          <td align="right" valign="top">
            <span style="display:inline-block;padding:3px 10px;border-radius:6px;font-size:10px;font-weight:700;letter-spacing:0.5px;color:{role_color};background:{role_color}18;border:1px solid {role_color}30;">{role}</span>
          </td>
        </tr>
      </table>
    </td></tr>
    </table>
  </td></tr>

  <!-- Details Grid -->
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="50%" style="padding:8px 0;border-bottom:1px solid rgba(148,163,184,0.06);">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Company</div>
          <div style="font-size:13px;color:#F1F5F9;font-weight:500;">{company}</div>
        </td>
        <td width="50%" style="padding:8px 0 8px 16px;border-bottom:1px solid rgba(148,163,184,0.06);">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Phone</div>
          <div style="font-size:13px;color:#F1F5F9;font-weight:500;">{phone}</div>
        </td>
      </tr>
      <tr>
        <td colspan="2" style="padding:8px 0;">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:3px;">Reason for Access</div>
          <div style="font-size:13px;color:#94A3B8;line-height:1.5;">{reason}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- CTA Button -->
  <tr><td style="padding:0 32px 24px;" align="center">
    <a href="https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html#settings" style="display:inline-block;padding:12px 32px;background:#06B6D4;color:#070B16;font-size:13px;font-weight:700;text-decoration:none;border-radius:8px;letter-spacing:0.5px;">Review &amp; Approve</a>
  </td></tr>

  <!-- Timestamp -->
  <tr><td style="padding:0 32px 12px;">
    <div style="font-size:10px;color:#4A5168;text-align:center;font-family:monospace;">{ts}</div>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:16px 32px;background:rgba(0,0,0,0.2);border-top:1px solid rgba(148,163,184,0.06);">
    <table width="100%"><tr>
      <td><span style="font-size:10px;color:#4A5168;">Aevus by Intrepid Logic LLC</span></td>
      <td align="right"><span style="font-size:8px;color:#4A5168;letter-spacing:1.5px;">SDVOSB</span></td>
    </tr></table>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""

        ses.send_email(
            FromEmailAddress="Aevus Notifications <info@intrepidlogic.io>",
            Destination={"ToAddresses": ["woody@intrepidlogic.io"]},
            Content={
                "Simple": {
                    "Subject": {"Data": "AEVUS Demo Signup: " + name + " — " + company, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html, "Charset": "UTF-8"},
                        "Text": {"Data": "New Aevus access request from " + name + " (" + email + ") at " + company + ". Role: " + role + ". Review: https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html#settings", "Charset": "UTF-8"}
                    }
                }
            },
        )
        logger.info("ses_notification_sent", email=data["email"])
    except Exception as e:
        logger.warning("ses_notification_failed", error=str(e))

    # Confirmation email to requester
    try:
        confirm_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#070B16;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#070B16;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F172A;border:1px solid rgba(148,163,184,0.12);border-radius:16px;overflow:hidden;">
  <tr><td style="padding:28px 32px 20px;background:linear-gradient(135deg,rgba(6,182,212,0.08),transparent);border-bottom:1px solid rgba(148,163,184,0.08);">
    <span style="font-size:22px;font-weight:700;letter-spacing:3px;color:#06B6D4;">AEVUS</span>
  </td></tr>
  <tr><td style="padding:24px 32px 16px;">
    <div style="font-size:16px;font-weight:600;color:#F1F5F9;margin-bottom:8px;">Hi {name},</div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
      Thank you for requesting access to the Aevus SCADA Intelligence Platform. We've received your request and an administrator will review it shortly.
    </div>
  </td></tr>
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" style="background:rgba(6,182,212,0.04);border:1px solid rgba(6,182,212,0.12);border-radius:12px;" cellpadding="16" cellspacing="0">
    <tr><td>
      <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#64748B;margin-bottom:8px;">Your Request</div>
      <div style="font-size:12px;color:#94A3B8;line-height:1.8;">
        <strong style="color:#F1F5F9;">Role:</strong> {role}<br>
        <strong style="color:#F1F5F9;">Company:</strong> {company}<br>
        <strong style="color:#F1F5F9;">Submitted:</strong> {ts}
      </div>
    </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 32px 20px;">
    <div style="font-size:12px;color:#94A3B8;line-height:1.6;">
      Once approved, you'll receive an email with your login credentials. In the meantime, you can explore the platform in demo mode:
    </div>
  </td></tr>
  <tr><td style="padding:0 32px 24px;" align="center">
    <a href="https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html?demo=true" style="display:inline-block;padding:12px 32px;background:#06B6D4;color:#070B16;font-size:13px;font-weight:700;text-decoration:none;border-radius:8px;letter-spacing:0.5px;">Explore Demo</a>
  </td></tr>
  <tr><td style="padding:16px 32px;background:rgba(0,0,0,0.2);border-top:1px solid rgba(148,163,184,0.06);">
    <table width="100%"><tr>
      <td><span style="font-size:10px;color:#4A5168;">Aevus by Intrepid Logic LLC</span></td>
      <td align="right"><span style="font-size:8px;color:#4A5168;letter-spacing:1.5px;">SDVOSB</span></td>
    </tr></table>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

        ses.send_email(
            FromEmailAddress="Aevus Platform <info@intrepidlogic.io>",
            Destination={"ToAddresses": [email]},
            Content={
                "Simple": {
                    "Subject": {"Data": "Aevus Access Request Received", "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": confirm_html, "Charset": "UTF-8"},
                        "Text": {"Data": "Hi " + name + ", thank you for requesting access to the Aevus SCADA Intelligence Platform. An administrator will review your request shortly. Explore the demo at: https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html?demo=true", "Charset": "UTF-8"}
                    }
                }
            },
        )
        logger.info("requester_confirmation_sent", email=email)
    except Exception as e:
        logger.warning("requester_confirmation_failed", error=str(e))

    return {"status": "ok", "id": data["id"]}


@router.get("/access-requests")
async def list_access_requests():
    return _load()


@router.put("/access-requests/{req_id}")
async def update_access_request(req_id: str, decision: AccessDecision):
    reqs = _load()
    target = None
    for r in reqs:
        if r.get("id") == req_id:
            target = r
            break

    if not target:
        return {"status": "error", "message": "Request not found"}

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

@router.get("/users")
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
        users.append({
            "username": u["Username"],
            "email": attrs.get("email", ""),
            "name": attrs.get("name", ""),
            "status": u["UserStatus"],
            "enabled": u["Enabled"],
            "created": u["UserCreateDate"].isoformat(),
            "modified": u.get("UserLastModifiedDate", u["UserCreateDate"]).isoformat(),
            "groups": gs,
        })
    return users


@router.put("/users/{username}/role")
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


@router.put("/users/{username}/toggle")
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


@router.delete("/users/{username}")
async def delete_user(username: str):
    """Permanently delete a Cognito user."""
    import boto3
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    cognito.admin_delete_user(UserPoolId=pool, Username=username)
    logger.info("user_deleted", username=username)
    return {"status": "ok"}


@router.post("/users/{username}/reset-password")
async def reset_user_password(username: str):
    """Force a password reset — sends new temp password via email."""
    import boto3
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    cognito.admin_reset_user_password(UserPoolId=pool, Username=username)
    logger.info("user_password_reset", username=username)
    return {"status": "ok"}

@router.post("/users/{username}/mfa")
async def enable_mfa(username: str):
    """Enable TOTP MFA for a user."""
    import boto3
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = "us-east-1_CVFBcLJV3"
    try:
        cognito.admin_set_user_mfa_preference(
            UserPoolId=pool,
            Username=username,
            SoftwareTokenMfaSettings={"Enabled": True, "PreferredMfa": True}
        )
        logger.info("mfa_enabled", username=username)
        return {"status": "ok"}
    except Exception as e:
        logger.warning("mfa_enable_failed", username=username, error=str(e))
        return {"status": "error", "error": str(e)}

