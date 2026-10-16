"""
Aevus -- Door 1 demo-user provisioning (Cognito, passwordless, least privilege).

Hard guarantees, each pinned by tests/test_demo_access.py:

* The ONLY group this module can ever add a user to is ``DEMO_GROUP``
  (``DemoViewer``, defined in src.api.auth). The group name is a module constant, never taken from a
  request, a record field, or a function argument. There is no code path that
  adds Admin / Operator / Viewer / Diagnostics.
* No password is ever created or delivered. The user is created with
  ``MessageAction=SUPPRESS`` (Cognito sends nothing), then a one-time code is
  requested through the passwordless ``USER_AUTH`` flow (EMAIL_OTP or SMS_OTP).
* An existing pool user who already holds any other group is left completely
  untouched (we never add to, remove from, or re-code a real account).
* If the group add fails after we created the user, the user is deleted again, so
  we never leave a group-less pool user (which the API treats as an ordinary
  authenticated user).

The demo group is synthetic-only: src/api/auth.py denies every live-data route to
any token carrying it. This module only creates identities; it adds no data path
and nothing here can reach field equipment (IL-9000 unchanged).

Cognito configuration this depends on (done by devops, NOT by this code; see the
PR description): app client with ALLOW_USER_AUTH, pool sign-in policy allowing
EMAIL_OTP (and SMS_OTP once enabled), the DemoViewer group, self sign-up disabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

import structlog
from botocore.exceptions import ClientError

from src.api.auth import COGNITO_POOL_ID, COGNITO_REGION, DEMO_GROUP

logger = structlog.get_logger()

_PHONE_RE: Final = re.compile(r"^\+[1-9]\d{7,14}$")


class ProvisioningError(Exception):
    """Cognito provisioning failed (the message is safe to log, not to show users)."""


def normalize_phone(raw: str) -> str:
    """Return an E.164 number or raise ValueError. Bare 10-digit input is treated as US."""
    digits = re.sub(r"[\s().-]", "", raw or "")
    if re.fullmatch(r"\d{10}", digits):
        digits = "+1" + digits
    elif re.fullmatch(r"1\d{10}", digits):
        digits = "+" + digits
    if not _PHONE_RE.match(digits):
        raise ValueError("invalid phone number")
    return digits


def get_cognito_client() -> Any:
    """Build the Cognito IDP client (isolated so tests can patch it)."""
    import boto3

    return boto3.client("cognito-idp", region_name=COGNITO_REGION)


@dataclass
class ProvisionResult:
    """Outcome of provision_demo_user."""

    status: str  # "created" | "reused" | "existing_account"
    username: str = ""
    groups: list[str] = field(default_factory=list)

    @property
    def usable_for_demo(self) -> bool:
        """True when a demo sign-in code may be sent for this identity."""
        return self.status in ("created", "reused")


def _code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def provision_demo_user(
    cognito: Any, *, email: str, name: str, phone: str = "", sms_enabled: bool = False
) -> ProvisionResult:
    """Create (or reuse) a passwordless Cognito user in DemoViewer and nothing else."""
    attrs = [
        {"Name": "email", "Value": email},
        # The one-time code later proves the address: only its owner can finish sign-in.
        {"Name": "email_verified", "Value": "true"},
        {"Name": "name", "Value": name},
    ]
    if sms_enabled and phone:
        # Self-attested number; SMS stays disabled by default (settings.demo_sms_otp_enabled).
        attrs += [{"Name": "phone_number", "Value": phone}, {"Name": "phone_number_verified", "Value": "true"}]

    created = False
    try:
        resp = cognito.admin_create_user(
            UserPoolId=COGNITO_POOL_ID,
            Username=email,
            UserAttributes=attrs,
            MessageAction="SUPPRESS",  # no invite email, no temporary password delivered
            ForceAliasCreation=False,
        )
        created = True
        username = resp.get("User", {}).get("Username", email)
    except ClientError as exc:
        if _code(exc) != "UsernameExistsException":
            raise ProvisioningError(f"admin_create_user failed: {_code(exc) or 'unknown'}") from exc
        username = email
        try:
            current = [
                g["GroupName"]
                for g in cognito.admin_list_groups_for_user(UserPoolId=COGNITO_POOL_ID, Username=username).get(
                    "Groups", []
                )
            ]
        except ClientError as exc2:
            raise ProvisioningError(f"admin_list_groups_for_user failed: {_code(exc2) or 'unknown'}") from exc2
        if any(g != DEMO_GROUP for g in current):
            # A real account (Operator/Admin/...). Never modify or send it a demo code.
            logger.warning("demo_provision_existing_account_untouched", groups=current)
            return ProvisionResult(status="existing_account", username=username, groups=current)

    try:
        cognito.admin_add_user_to_group(UserPoolId=COGNITO_POOL_ID, Username=username, GroupName=DEMO_GROUP)
    except ClientError as exc:
        if created:
            try:
                cognito.admin_delete_user(UserPoolId=COGNITO_POOL_ID, Username=username)
            except ClientError:
                logger.error("demo_provision_rollback_failed")
        raise ProvisioningError(f"admin_add_user_to_group failed: {_code(exc) or 'unknown'}") from exc

    logger.info("demo_user_provisioned", created=created, group=DEMO_GROUP)
    return ProvisionResult(status="created" if created else "reused", username=username, groups=[DEMO_GROUP])


@dataclass
class CodeResult:
    """Result of requesting a one-time sign-in code."""

    challenge: str
    session: str
    available: list[str] = field(default_factory=list)


def send_login_code(cognito: Any, *, client_id: str, email: str, delivery: str = "email") -> CodeResult:
    """Ask Cognito to deliver an EMAIL_OTP / SMS_OTP via the passwordless USER_AUTH flow.

    The returned ``session`` is the standard Cognito challenge session; the browser
    completes it with RespondToAuthChallenge and the code. The session alone is
    useless without the code, which only the address/number owner receives.
    """
    if not client_id:
        raise ProvisioningError("DEMO_COGNITO_CLIENT_ID is not configured")
    preferred = "SMS_OTP" if delivery == "sms" else "EMAIL_OTP"
    try:
        resp = cognito.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_AUTH",
            AuthParameters={"USERNAME": email, "PREFERRED_CHALLENGE": preferred},
        )
    except ClientError as exc:
        raise ProvisioningError(f"initiate_auth failed: {_code(exc) or 'unknown'}") from exc
    return CodeResult(
        challenge=resp.get("ChallengeName", ""),
        session=resp.get("Session", ""),
        available=list(resp.get("AvailableChallenges", [])),
    )
