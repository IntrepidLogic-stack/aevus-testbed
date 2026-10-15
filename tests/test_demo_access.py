"""Door 1 (gated synthetic demo) access tests.

Covers: domain classification, the business / free-mail gate, DemoViewer-only
provisioning, the signed one-time approve link, server-side synthetic-only
enforcement, the HubSpot push no-op, the abuse controls, and the durable store.

Real middleware + real routers + real RS256 JWTs signed by a throwaway key (the
JWKS client is faked, so no network). Cognito and SES are mocks, so nothing here
can reach AWS or HubSpot.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api import access_requests, auth, demo_access
from src.config import settings
from src.integrations import hubspot
from src.services import approve_link, demo_provisioning
from src.services.email_domains import InvalidEmailError, classify_email, normalize_email

MASTER_KEY = "real-secret-key"
SIGNING_KEY = "k" * 48
GOOD_PHONE = "281-555-0142"
# Use the exact class the code under test catches: tests/lambda/test_rca_context.py
# swaps botocore.exceptions.ClientError in sys.modules, which would otherwise differ.
_ClientError = demo_provisioning.ClientError


def ClientError(response: dict, operation: str) -> Exception:  # noqa: N802
    """Build the error with a ``.response`` even when the stub class lacks one."""
    err = _ClientError(response, operation)
    if not hasattr(err, "response"):
        err.response = response
    return err


# ── domain classification ────────────────────────────────────────────────────


class TestDomainClassification:
    @pytest.mark.parametrize(
        "email",
        [
            "a@gmail.com",
            "a@Yahoo.com",
            "a@sbcglobal.net",
            "a@outlook.com",
            "a@hotmail.com",
            "a@aol.com",
            "a@icloud.com",
            "a@proton.me",
            "a@protonmail.com",
            "a@yahoo.co.uk",
            "a@hotmail.fr",
            "a@outlook.de",
            "a@mail.yahoo.com",
            "a@mailinator.com",
            "a@att.net",
            "a@comcast.net",
        ],
    )
    def test_free_mail(self, email):
        assert classify_email(normalize_email(email)) == "free_mail"

    @pytest.mark.parametrize(
        "email",
        [
            "pat@kinetik.com",
            "pat@acme-midstream.com",
            "pat@energytransfer.com",
            "pat@outlook.acme.com",
            "pat@acme.me.uk",
        ],
    )
    def test_business(self, email):
        assert classify_email(normalize_email(email)) == "business"

    def test_lookalike_suffix_is_not_free_mail(self):
        # "acme.com" must not match the "me.com" entry by raw string suffix.
        assert classify_email("pat@acme.com") == "business"

    @pytest.mark.parametrize(
        "bad", ["", "nope", "a@b", "a b@acme.com", "a@acme.com\nBcc: x@evil.com", "a@@acme.com", "x" * 300 + "@a.com"]
    )
    def test_invalid_emails_rejected(self, bad):
        with pytest.raises(InvalidEmailError):
            normalize_email(bad)

    def test_normalizes_case_and_whitespace(self):
        assert normalize_email("  Pat@ACME.com ") == "pat@acme.com"


# ── signed one-time token ────────────────────────────────────────────────────


class TestApproveToken:
    def test_roundtrip(self):
        tok, nonce_hash = approve_link.issue_token("0007", SIGNING_KEY, 60)
        c = approve_link.verify_token(tok, SIGNING_KEY)
        assert c.request_id == "0007"
        assert approve_link.hash_nonce(c.nonce) == nonce_hash

    def test_expired(self):
        tok, _ = approve_link.issue_token("0007", SIGNING_KEY, 60, now=time.time() - 120)
        with pytest.raises(approve_link.ApproveTokenExpiredError):
            approve_link.verify_token(tok, SIGNING_KEY)

    def test_tampered_payload_and_wrong_key_fail(self):
        tok, _ = approve_link.issue_token("0007", SIGNING_KEY, 60)
        payload, sig = tok.split(".")
        forged_payload, _ = approve_link.issue_token("0099", SIGNING_KEY, 60)[0].split(".")
        with pytest.raises(approve_link.ApproveTokenInvalidError):
            approve_link.verify_token(f"{forged_payload}.{sig}", SIGNING_KEY)
        with pytest.raises(approve_link.ApproveTokenInvalidError):
            approve_link.verify_token(tok, "z" * 48)

    @pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "a.b", "." * 3, "x" * 2000])
    def test_garbage_rejected(self, junk):
        with pytest.raises(approve_link.ApproveTokenInvalidError):
            approve_link.verify_token(junk, SIGNING_KEY)

    def test_fails_closed_without_key(self):
        with pytest.raises(approve_link.ApproveKeyMissingError):
            approve_link.issue_token("1", "", 60)
        with pytest.raises(approve_link.ApproveKeyMissingError):
            approve_link.issue_token("1", "short", 60)
        tok, _ = approve_link.issue_token("1", SIGNING_KEY, 60)
        with pytest.raises(approve_link.ApproveKeyMissingError):
            approve_link.verify_token(tok, "")


# ── app fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def trusted_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, groups, **extra) -> str:
    now = int(time.time())
    claims = {"sub": "sub-1", "iss": auth.COGNITO_ISSUER, "token_use": "id", "iat": now, "exp": now + 3600, **extra}
    if groups is not None:
        claims["cognito:groups"] = groups
    return jwt.encode(claims, key, algorithm="RS256")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cognito():
    c = MagicMock(name="cognito-idp")
    c.admin_create_user.return_value = {"User": {"Username": "sub-123"}}
    c.initiate_auth.return_value = {"ChallengeName": "EMAIL_OTP", "Session": "sess-abc"}
    return c


@pytest.fixture
def ses():
    """Patch boto3.client (SES) and expose the sent-email calls."""
    client = MagicMock(name="sesv2")
    with patch("boto3.client", return_value=client):
        yield client


@pytest.fixture
def env(tmp_path, monkeypatch, cognito):
    """Isolated store + Door 1 enabled + generous limits + mocked Cognito."""
    monkeypatch.setattr(access_requests, "DATA_FILE", tmp_path / "data" / "access_requests.json")
    monkeypatch.setattr(access_requests, "LEGACY_DATA_FILE", tmp_path / "legacy" / "access_requests.json")
    monkeypatch.setattr(settings, "demo_access_enabled", True)
    monkeypatch.setattr(settings, "access_approve_signing_key", SIGNING_KEY)
    monkeypatch.setattr(settings, "access_approve_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "demo_cognito_client_id", "client-123")
    monkeypatch.setattr(settings, "demo_sms_otp_enabled", False)
    monkeypatch.setattr(settings, "hubspot_private_app_token", "")
    monkeypatch.setattr(settings, "access_rl_ip_limit", 100)
    monkeypatch.setattr(settings, "access_rl_email_limit", 100)
    monkeypatch.setattr(settings, "access_rl_window_seconds", 3600)
    monkeypatch.setattr(settings, "access_trusted_proxy_hops", 1)
    monkeypatch.setattr(settings, "demo_domain_daily_cap", 10)
    monkeypatch.setattr(settings, "access_notify_to", "woody@intrepidlogic.io")
    monkeypatch.setattr(access_requests, "get_cognito_client", lambda: cognito)
    for lim in (access_requests.ip_limiter, access_requests.email_limiter, demo_access.code_limiter):
        lim.reset()
    return SimpleNamespace(store=tmp_path / "data" / "access_requests.json", cognito=cognito)


@pytest.fixture
def client(env, ses, trusted_key, monkeypatch):
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=trusted_key.public_key()))
    monkeypatch.setattr(auth, "_jwk_client", fake_jwks)
    monkeypatch.setattr(auth, "settings", SimpleNamespace(api_key=MASTER_KEY, api_key_header="X-API-Key"))

    live = APIRouter()

    @live.get("/assets")
    async def _assets():
        return [{"id": "REAL-RTU-01"}]  # stands in for any live-data route

    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)
    app.include_router(access_requests.router, prefix="/api/v1")
    app.include_router(demo_access.router, prefix="/api/v1")
    app.include_router(live, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


def _form(**over):
    body = {
        "flow": "demo",
        "name": "Pat Lee",
        "email": "pat@acme-midstream.com",
        "company": "Acme Midstream",
        "role": "SCADA Manager",
        "phone": GOOD_PHONE,
    }
    body.update(over)
    return body


def _records(env) -> list[dict]:
    return json.loads(env.store.read_text())


def _sent_to(ses, address: str) -> list[dict]:
    return [c.kwargs for c in ses.send_email.call_args_list if address in c.kwargs["Destination"]["ToAddresses"]]


def _approve_token_from_email(ses) -> str:
    texts = [c["Content"]["Simple"]["Body"]["Text"]["Data"] for c in _sent_to(ses, "woody@intrepidlogic.io")]
    m = re.search(r"approve\.html#t=([A-Za-z0-9_.-]+)", " ".join(texts))
    assert m, texts
    return m.group(1)


# ── business domain: auto-provision, DemoViewer only ─────────────────────────


class TestBusinessAutoProvision:
    def test_business_domain_provisions_demoviewer_only(self, client, env, ses):
        r = client.post("/api/v1/access-requests", json=_form())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "code_sent"
        assert body["challenge"] == "EMAIL_OTP"
        assert body["session"] == "sess-abc"

        # Every group add is DemoViewer, and nothing else is ever added.
        adds = env.cognito.admin_add_user_to_group.call_args_list
        assert len(adds) == 1
        assert adds[0].kwargs["GroupName"] == "DemoViewer"

        # Passwordless: no temporary password, no invite message.
        create = env.cognito.admin_create_user.call_args.kwargs
        assert "TemporaryPassword" not in create
        assert create["MessageAction"] == "SUPPRESS"
        assert create["Username"] == "pat@acme-midstream.com"
        env.cognito.admin_set_user_password.assert_not_called()

        # Code delivered through USER_AUTH EMAIL_OTP.
        ia = env.cognito.initiate_auth.call_args.kwargs
        assert ia["AuthFlow"] == "USER_AUTH"
        assert ia["AuthParameters"]["PREFERRED_CHALLENGE"] == "EMAIL_OTP"
        assert ia["ClientId"] == "client-123"

        rec = _records(env)[0]
        assert rec["status"] == "provisioned"
        assert rec["flow"] == "demo"
        assert rec["domain_class"] == "business"
        assert rec["role"] == "demo"
        assert rec["job_role"] == "SCADA Manager"
        assert "approve_nonce_sha256" not in rec

    def test_sms_requested_but_disabled_falls_back_to_email_and_no_phone_attr(self, client, env, ses):
        client.post("/api/v1/access-requests", json=_form(delivery="sms"))
        assert env.cognito.initiate_auth.call_args.kwargs["AuthParameters"]["PREFERRED_CHALLENGE"] == "EMAIL_OTP"
        attrs = {a["Name"] for a in env.cognito.admin_create_user.call_args.kwargs["UserAttributes"]}
        assert "phone_number" not in attrs

    def test_sms_path_when_enabled_marks_number(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "demo_sms_otp_enabled", True)
        client.post("/api/v1/access-requests", json=_form(delivery="sms"))
        assert env.cognito.initiate_auth.call_args.kwargs["AuthParameters"]["PREFERRED_CHALLENGE"] == "SMS_OTP"
        attrs = {a["Name"]: a["Value"] for a in env.cognito.admin_create_user.call_args.kwargs["UserAttributes"]}
        assert attrs["phone_number"] == "+12815550142"

    def test_existing_real_account_is_untouched(self, client, env, ses):
        env.cognito.admin_create_user.side_effect = ClientError(
            {"Error": {"Code": "UsernameExistsException", "Message": "x"}}, "AdminCreateUser"
        )
        env.cognito.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "Operator"}]}
        r = client.post("/api/v1/access-requests", json=_form())
        assert r.json()["status"] == "received"  # generic: does not reveal the account exists
        env.cognito.admin_add_user_to_group.assert_not_called()
        env.cognito.admin_remove_user_from_group.assert_not_called()
        env.cognito.initiate_auth.assert_not_called()
        assert _records(env)[0]["status"] == "existing_account"

    def test_group_add_failure_rolls_back_the_new_user(self, client, env, ses):
        env.cognito.admin_add_user_to_group.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "no group"}}, "AdminAddUserToGroup"
        )
        r = client.post("/api/v1/access-requests", json=_form())
        assert r.json()["status"] == "received"
        env.cognito.admin_delete_user.assert_called_once()  # never leave a group-less pool user
        env.cognito.initiate_auth.assert_not_called()
        assert _records(env)[0]["status"] == "provision_failed"

    def test_only_demo_group_name_appears_in_provisioning_source(self):
        src = Path(demo_provisioning.__file__).read_text()
        calls = re.findall(r"admin_add_user_to_group\((.*?)\)", src, re.S)
        assert calls and all("GroupName=DEMO_GROUP" in c for c in calls)
        assert auth.DEMO_GROUP == "DemoViewer"
        for forbidden in ("Operator", "Admin", "Diagnostics"):
            assert f'GroupName="{forbidden}"' not in src

    def test_domain_daily_cap_routes_to_review(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "demo_domain_daily_cap", 1)
        a = client.post("/api/v1/access-requests", json=_form(email="a@acme-midstream.com"))
        b = client.post("/api/v1/access-requests", json=_form(email="b@acme-midstream.com"))
        assert a.json()["status"] == "code_sent"
        assert b.json()["status"] == "pending_review"
        assert env.cognito.admin_create_user.call_count == 1
        assert _records(env)[1]["review_reason"] == "domain_daily_cap"

    def test_feature_flag_off_provisions_nothing(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "demo_access_enabled", False)
        r = client.post("/api/v1/access-requests", json=_form())
        assert r.json()["status"] == "pending_review"
        env.cognito.admin_create_user.assert_not_called()
        assert "approve_nonce_sha256" not in _records(env)[0]


# ── free-mail: hold, signed one-time approve ─────────────────────────────────


class TestFreeMailGate:
    def test_free_mail_is_pending_review_and_not_provisioned(self, client, env, ses):
        r = client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_review"
        assert "session" not in r.json()
        env.cognito.admin_create_user.assert_not_called()
        env.cognito.admin_add_user_to_group.assert_not_called()
        env.cognito.initiate_auth.assert_not_called()
        rec = _records(env)[0]
        assert rec["status"] == "pending_review"
        assert rec["domain_class"] == "free_mail"
        assert rec["approve_nonce_sha256"]

    def test_notification_carries_signed_link_and_requester_ack(self, client, env, ses):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        notice = _sent_to(ses, "woody@intrepidlogic.io")[0]
        html_body = notice["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "approve.html#t=" in html_body
        verified = approve_link.verify_token(_approve_token_from_email(ses), SIGNING_KEY)
        assert verified.request_id == "0001"
        assert _sent_to(ses, "pat@gmail.com")  # acknowledgement, no access granted yet

    def test_approve_requires_admin(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        tok = _approve_token_from_email(ses)
        body = {"token": tok}
        assert client.post("/api/v1/demo-access/approve", json=body).status_code == 401
        assert (
            client.post("/api/v1/demo-access/approve", json=body, headers={"X-API-Key": MASTER_KEY}).status_code == 403
        )
        for groups in (["Viewer"], ["Operator"], ["DemoViewer"], []):
            h = _bearer(_token(trusted_key, groups))
            assert client.post("/api/v1/demo-access/approve", json=body, headers=h).status_code == 403, groups
        env.cognito.admin_create_user.assert_not_called()
        assert _records(env)[0]["status"] == "pending_review"

    def test_approve_provisions_demoviewer_and_is_single_use(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        tok = _approve_token_from_email(ses)
        admin = _bearer(_token(trusted_key, ["Admin"], email="dave@intrepidlogic.io"))

        r = client.post("/api/v1/demo-access/approve", json={"token": tok}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "provisioned"
        assert [c.kwargs["GroupName"] for c in env.cognito.admin_add_user_to_group.call_args_list] == ["DemoViewer"]
        rec = _records(env)[0]
        assert rec["status"] == "provisioned"
        assert rec["approved_by"] == "dave@intrepidlogic.io"
        assert "approve_nonce_sha256" not in rec
        # Prospect is told they are approved (login link), no code pushed while they are away.
        assert _sent_to(ses, "pat@gmail.com")
        env.cognito.initiate_auth.assert_not_called()

        # Replay: the same valid, unexpired token cannot be used again.
        again = client.post("/api/v1/demo-access/approve", json={"token": tok}, headers=admin)
        assert again.status_code == 409
        assert env.cognito.admin_create_user.call_count == 1

    def test_expired_token_is_410_and_provisions_nothing(self, client, env, ses, trusted_key, monkeypatch):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        rec = _records(env)[0]
        tok, nonce_hash = approve_link.issue_token(rec["id"], SIGNING_KEY, 60, now=time.time() - 3600)
        rec["approve_nonce_sha256"] = nonce_hash
        env.store.write_text(json.dumps([rec]))
        r = client.post(
            "/api/v1/demo-access/approve", json={"token": tok}, headers=_bearer(_token(trusted_key, ["Admin"]))
        )
        assert r.status_code == 410
        env.cognito.admin_create_user.assert_not_called()

    def test_tampered_or_foreign_token_is_400(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        admin = _bearer(_token(trusted_key, ["Admin"]))
        tok = _approve_token_from_email(ses)
        payload, sig = tok.split(".")
        assert (
            client.post(
                "/api/v1/demo-access/approve", json={"token": f"{payload}.{sig[:-2]}AA"}, headers=admin
            ).status_code
            == 400
        )
        wrong_key_tok, _ = approve_link.issue_token("0001", "q" * 48, 60)
        assert (
            client.post("/api/v1/demo-access/approve", json={"token": wrong_key_tok}, headers=admin).status_code == 400
        )
        env.cognito.admin_create_user.assert_not_called()

    def test_token_for_one_request_cannot_approve_another(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="a@gmail.com", name="A"))
        tok_a = _approve_token_from_email(ses)
        ses.send_email.reset_mock()
        client.post("/api/v1/access-requests", json=_form(email="b@gmail.com", name="B"))
        # Splice A's valid signature onto B's payload: must fail.
        tok_b = _approve_token_from_email(ses)
        spliced = tok_b.split(".")[0] + "." + tok_a.split(".")[1]
        admin = _bearer(_token(trusted_key, ["Admin"]))
        assert client.post("/api/v1/demo-access/approve", json={"token": spliced}, headers=admin).status_code == 400

    def test_manual_decision_voids_the_emailed_link(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        tok = _approve_token_from_email(ses)
        admin = _bearer(_token(trusted_key, ["Admin"]))
        client.put("/api/v1/access-requests/0001", json={"status": "denied"}, headers=admin)
        assert client.post("/api/v1/demo-access/approve", json={"token": tok}, headers=admin).status_code == 409
        env.cognito.admin_create_user.assert_not_called()

    def test_legacy_put_cannot_temp_password_provision_a_demo_record(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        admin = _bearer(_token(trusted_key, ["Admin"]))
        r = client.put(
            "/api/v1/access-requests/0001", json={"status": "approved", "cognito_create": True}, headers=admin
        )
        assert r.json()["status"] == "error"
        env.cognito.admin_create_user.assert_not_called()

    def test_approve_fails_closed_without_signing_key(self, client, env, ses, trusted_key, monkeypatch):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        tok = _approve_token_from_email(ses)
        monkeypatch.setattr(settings, "access_approve_signing_key", "")
        r = client.post(
            "/api/v1/demo-access/approve", json={"token": tok}, headers=_bearer(_token(trusted_key, ["Admin"]))
        )
        assert r.status_code == 503
        env.cognito.admin_create_user.assert_not_called()

    def test_no_signing_key_means_no_link_in_email(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "access_approve_signing_key", "")
        r = client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        assert r.json()["status"] == "pending_review"
        text = _sent_to(ses, "woody@intrepidlogic.io")[0]["Content"]["Simple"]["Body"]["Text"]["Data"]
        assert "approve.html" not in text
        assert "approve_nonce_sha256" not in _records(env)[0]

    def test_provision_failure_after_approve_is_retryable_by_admin(self, client, env, ses, trusted_key):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        tok = _approve_token_from_email(ses)
        admin = _bearer(_token(trusted_key, ["Admin"]))
        env.cognito.admin_create_user.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException"}}, "AdminCreateUser"
        )
        assert client.post("/api/v1/demo-access/approve", json={"token": tok}, headers=admin).status_code == 502
        assert _records(env)[0]["status"] == "provision_failed"
        env.cognito.admin_create_user.side_effect = None
        env.cognito.admin_create_user.return_value = {"User": {"Username": "sub-9"}}
        ok = client.post("/api/v1/demo-access/requests/0001/provision", headers=admin)
        assert ok.json()["status"] == "provisioned"
        # A pending (never approved) record cannot be force-provisioned through the retry route.
        client.post("/api/v1/access-requests", json=_form(email="x@gmail.com", name="X"))
        assert client.post("/api/v1/demo-access/requests/0002/provision", headers=admin).status_code == 409


# ── public code endpoint ─────────────────────────────────────────────────────


class TestCodeEndpoint:
    def test_provisioned_user_gets_code_and_shape_matches_decoy(self, client, env, ses):
        client.post("/api/v1/access-requests", json=_form())
        env.cognito.initiate_auth.reset_mock()
        real = client.post("/api/v1/demo-access/code", json={"email": "pat@acme-midstream.com"}).json()
        decoy = client.post("/api/v1/demo-access/code", json={"email": "nobody@acme-midstream.com"}).json()
        assert real["session"] == "sess-abc"
        assert env.cognito.initiate_auth.call_count == 1  # decoy never touched Cognito
        assert set(real) == set(decoy) == {"status", "challenge", "session"}

    def test_pending_free_mail_user_gets_decoy_not_a_code(self, client, env, ses):
        client.post("/api/v1/access-requests", json=_form(email="pat@gmail.com"))
        client.post("/api/v1/demo-access/code", json={"email": "pat@gmail.com"})
        env.cognito.initiate_auth.assert_not_called()

    def test_public_route_needs_no_credentials(self, client, env, ses):
        assert client.post("/api/v1/demo-access/code", json={"email": "x@acme.com"}).status_code == 200


# ── server-side synthetic-only enforcement ───────────────────────────────────


class TestDemoViewerCannotReachLive:
    def test_demoviewer_denied_live_route(self, client, trusted_key):
        h = _bearer(_token(trusted_key, ["DemoViewer"]))
        r = client.get("/api/v1/assets", headers=h)
        assert r.status_code == 403
        assert "synthetic" in r.json()["detail"]

    def test_demoviewer_cannot_select_live_by_param_header_or_master_key(self, client, trusted_key):
        h = _bearer(_token(trusted_key, ["DemoViewer"]))
        attempts = [
            {"params": {"source": "live"}, "headers": h},
            {"params": {"data_source": "live", "demo": "false"}, "headers": h},
            {"headers": {**h, "X-Aevus-Data-Source": "live"}},
            {"headers": {**h, "X-API-Key": MASTER_KEY}},
        ]
        for kw in attempts:
            assert client.get("/api/v1/assets", **kw).status_code == 403, kw

    def test_deny_wins_when_demoviewer_is_combined_with_other_groups(self, client, trusted_key):
        for groups in (["DemoViewer", "Operator"], ["DemoViewer", "Admin"], ["Viewer", "DemoViewer"]):
            h = _bearer(_token(trusted_key, groups))
            assert client.get("/api/v1/assets", headers=h).status_code == 403, groups
            assert client.get("/api/v1/access-requests", headers=h).status_code == 403, groups

    def test_demoviewer_denied_on_real_app_data_routes(self, trusted_key, monkeypatch):
        from src.main import app

        monkeypatch.setattr(
            auth,
            "_jwk_client",
            SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=trusted_key.public_key())),
        )
        monkeypatch.setattr(auth, "settings", SimpleNamespace(api_key=MASTER_KEY, api_key_header="X-API-Key"))
        h = _bearer(_token(trusted_key, ["DemoViewer"]))
        c = TestClient(app)  # no lifespan: only the middleware decision is under test
        for path in (
            "/api/v1/assets",
            "/api/v1/alerts",
            "/api/v1/health/summary",
            "/api/v1/predictions",
            "/api/v1/users",
        ):
            r = c.get(path, headers=h)
            assert r.status_code == 403, path
            assert "synthetic" in r.json().get("detail", "") or path == "/api/v1/users"

    def test_session_probe_reports_synthetic_and_not_live(self, client, trusted_key):
        r = client.get("/api/v1/demo-access/session", headers=_bearer(_token(trusted_key, ["DemoViewer"])))
        assert r.status_code == 200
        assert r.json() == {"identity": "demo", "data_source": "synthetic", "live_allowed": False}

    def test_standard_users_are_unaffected(self, client, trusted_key):
        h = _bearer(_token(trusted_key, ["Viewer"]))
        assert client.get("/api/v1/assets", headers=h).status_code == 200
        assert client.get("/api/v1/demo-access/session", headers=h).json()["live_allowed"] is True

    def test_session_requires_a_bearer(self, client):
        assert client.get("/api/v1/demo-access/session").status_code == 401

    def test_first_login_marked_once_and_pushed_once(self, client, env, ses, trusted_key, monkeypatch):
        push = AsyncMock(return_value=True)
        monkeypatch.setattr(demo_access, "push_access_event", push)
        client.post("/api/v1/access-requests", json=_form())
        h = _bearer(_token(trusted_key, ["DemoViewer"], email="pat@acme-midstream.com"))
        client.get("/api/v1/demo-access/session", headers=h)
        client.get("/api/v1/demo-access/session", headers=h)
        assert [c.args[0].event for c in push.call_args_list] == ["first_login"]
        assert _records(env)[0]["first_login_at"]


# ── HubSpot push ─────────────────────────────────────────────────────────────


def _event(**over) -> hubspot.AccessEvent:
    base = {
        "event": "requested",
        "request_id": "0001",
        "email": "pat@acme-midstream.com",
        "name": "Pat Lee",
        "company": "Acme Midstream",
    }
    base.update(over)
    return hubspot.AccessEvent(**base)


def _mock_hubspot(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(**kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(**kw)

    monkeypatch.setattr(hubspot.httpx, "AsyncClient", factory)


class TestHubSpotPush:
    async def test_noop_without_token(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "")

        def boom(**_kw):
            raise AssertionError("no HTTP client may be built without a token")

        monkeypatch.setattr(hubspot.httpx, "AsyncClient", boom)
        assert hubspot.hubspot_enabled() is False
        assert await hubspot.push_access_event(_event()) is False

    async def test_pushes_contact_company_deal_in_comms_pipeline(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "test-token-not-real")
        monkeypatch.setattr(settings, "hubspot_dealstage_id", "4438755006")
        calls: list[tuple[str, str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else {}
            calls.append((request.method, request.url.path, body))
            assert request.headers["authorization"] == "Bearer test-token-not-real"
            p = request.url.path
            if p.endswith("contacts/batch/upsert"):
                return httpx.Response(200, json={"results": [{"id": "11"}]})
            if p.endswith("companies/search") or p.endswith("deals/search"):
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={"id": "99"})

        _mock_hubspot(monkeypatch, handler)
        assert await hubspot.push_access_event(_event()) is True

        deal = next(b for m, p, b in calls if p.endswith("/objects/deals") and m == "POST")
        assert deal["properties"]["pipeline"] == "2622266105"  # explicit, never the default pipeline
        assert deal["properties"]["dealstage"] == "4438755006"
        assert deal["properties"]["hubspot_owner_id"] == "166564401"
        company = next(b for m, p, b in calls if p.endswith("/objects/companies") and m == "POST")
        assert company["properties"]["domain"] == "acme-midstream.com"
        assert any(p.endswith("/objects/notes") for _, p, _ in calls)

    async def test_reuses_existing_company_and_deal(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "t")
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(f"{request.method} {request.url.path}")
            p = request.url.path
            if p.endswith("contacts/batch/upsert"):
                return httpx.Response(200, json={"results": [{"id": "11"}]})
            if p.endswith("/search"):
                return httpx.Response(200, json={"results": [{"id": "55"}]})
            return httpx.Response(200, json={"id": "99"})

        _mock_hubspot(monkeypatch, handler)
        assert await hubspot.push_access_event(_event(event="first_login")) is True
        assert "POST /crm/v3/objects/companies" not in seen
        assert "POST /crm/v3/objects/deals" not in seen

    async def test_free_mail_never_creates_or_attaches_a_company(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "t")
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path.endswith("contacts/batch/upsert"):
                return httpx.Response(200, json={"results": [{"id": "11"}]})
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={"id": "99"})

        _mock_hubspot(monkeypatch, handler)
        assert await hubspot.push_access_event(_event(email="pat@gmail.com", domain_class="free_mail")) is True
        assert not any("companies" in p for p in seen)

    async def test_failure_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "t")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        _mock_hubspot(monkeypatch, handler)
        assert await hubspot.push_access_event(_event()) is False  # no exception

    async def test_refuses_to_create_deal_without_stage(self, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "t")
        monkeypatch.setattr(settings, "hubspot_dealstage_id", "")

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not call HubSpot without an explicit stage")

        _mock_hubspot(monkeypatch, handler)
        assert await hubspot.push_access_event(_event()) is False

    def test_hubspot_outage_does_not_fail_provisioning(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "hubspot_private_app_token", "t")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        _mock_hubspot(monkeypatch, handler)
        r = client.post("/api/v1/access-requests", json=_form())
        assert r.status_code == 200
        assert r.json()["status"] == "code_sent"
        assert _records(env)[0]["status"] == "provisioned"

    def test_events_fire_on_request_and_provision(self, client, env, ses, monkeypatch):
        push = AsyncMock(return_value=True)
        monkeypatch.setattr(access_requests, "push_access_event", push)
        client.post("/api/v1/access-requests", json=_form())
        assert [c.args[0].event for c in push.call_args_list] == ["requested", "provisioned"]


# ── abuse controls and validation ────────────────────────────────────────────


class TestAbuseControls:
    def test_per_ip_rate_limit(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "access_rl_ip_limit", 2)
        codes = [
            client.post("/api/v1/access-requests", json=_form(email=f"u{i}@gmail.com")).status_code for i in range(3)
        ]
        assert codes == [200, 200, 429]

    def test_per_email_rate_limit(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "access_rl_email_limit", 2)
        codes = [
            client.post("/api/v1/access-requests", json=_form(email="same@gmail.com")).status_code for _ in range(3)
        ]
        assert codes == [200, 200, 429]
        # case/whitespace variants share the bucket
        assert client.post("/api/v1/access-requests", json=_form(email=" SAME@gmail.com ")).status_code == 429

    def test_spoofed_first_xff_hop_does_not_evade_ip_limit(self, client, env, ses, monkeypatch):
        monkeypatch.setattr(settings, "access_rl_ip_limit", 1)
        h1 = {"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}
        h2 = {"X-Forwarded-For": "2.2.2.2, 203.0.113.9"}  # attacker varies the leftmost entry
        assert client.post("/api/v1/access-requests", json=_form(email="a@gmail.com"), headers=h1).status_code == 200
        assert client.post("/api/v1/access-requests", json=_form(email="b@gmail.com"), headers=h2).status_code == 429

    @pytest.mark.parametrize(
        "over",
        [
            {"email": "not-an-email"},
            {"name": ""},
            {"name": "x" * 101},
            {"name": "Pat\nBcc: evil@x.com"},
            {"company": ""},
            {"phone": "12"},
            {"phone": "not a phone"},
            {"role": "r" * 81},
            {"flow": "admin"},
        ],
    )
    def test_payload_validation(self, client, env, ses, over):
        assert client.post("/api/v1/access-requests", json=_form(**over)).status_code == 422
        env.cognito.admin_create_user.assert_not_called()

    def test_client_cannot_set_status_or_groups(self, client, env, ses):
        r = client.post(
            "/api/v1/access-requests",
            json=_form(email="pat@gmail.com", status="approved", group="Admin", cognito_groups=["Admin"]),
        )
        assert r.json()["status"] == "pending_review"
        assert _records(env)[0]["status"] == "pending_review"
        env.cognito.admin_add_user_to_group.assert_not_called()


# ── email content (bug fix A1) and escaping ──────────────────────────────────


class TestNotificationEmail:
    def test_legacy_review_link_points_at_admin_page(self, client, env, ses):
        r = client.post("/api/v1/access-requests", json={"name": "Pat", "email": "pat@example.com", "company": "Acme"})
        assert r.json()["status"] == "ok"
        notice = _sent_to(ses, "woody@intrepidlogic.io")[0]["Content"]["Simple"]["Body"]
        assert 'href="https://aevus.intrepidlogic.io/dashboard/admin.html"' in notice["Html"]["Data"]
        assert "https://aevus.intrepidlogic.io/dashboard/admin.html" in notice["Text"]["Data"]
        assert "Aevus_Console.html#settings" not in notice["Html"]["Data"] + notice["Text"]["Data"]

    def test_user_supplied_text_is_html_escaped(self, client, env, ses):
        client.post(
            "/api/v1/access-requests",
            json={
                "name": "<script>alert(1)</script>",
                "email": "pat@example.com",
                "company": "<img src=x onerror=1>",
                "reason": "<b>hi</b>",
            },
        )
        body = _sent_to(ses, "woody@intrepidlogic.io")[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "<script>alert(1)" not in body
        assert "&lt;script&gt;" in body
        assert "<img src=x" not in body


# ── durable store (bug fix A2) ───────────────────────────────────────────────


class TestDurableStore:
    def test_default_store_is_outside_the_git_tree(self):
        repo_root = Path(__file__).resolve().parents[1]
        assert repo_root not in Path(access_requests.DATA_FILE).resolve().parents
        assert type(settings).model_fields["aevus_data_dir"].default == "/home/ubuntu/aevus-data"

    def test_migrates_legacy_file_once_and_never_overwrites_afterwards(self, tmp_path, monkeypatch):
        legacy = tmp_path / "tree" / "access_requests.json"
        new = tmp_path / "aevus-data" / "access_requests.json"
        legacy.parent.mkdir()
        legacy.write_text(json.dumps([{"id": "0001", "email": "george@x.com", "status": "pending"}]))
        monkeypatch.setattr(access_requests, "DATA_FILE", new)
        monkeypatch.setattr(access_requests, "LEGACY_DATA_FILE", legacy)

        # Graceful read before migration.
        assert access_requests._load()[0]["email"] == "george@x.com"
        access_requests.ensure_data_dir()
        assert json.loads(new.read_text())[0]["email"] == "george@x.com"

        # Simulate `git reset --hard` reverting the in-tree file to an old seed.
        legacy.write_text(json.dumps([{"id": "0001", "email": "old-seed@x.com"}]))
        access_requests.mutate(lambda reqs: reqs.append({"id": "0002", "email": "new@x.com"}))
        access_requests.ensure_data_dir()
        emails = [r["email"] for r in access_requests._load()]
        assert emails == ["george@x.com", "new@x.com"]  # live store untouched by the reverted file

    def test_creates_data_dir_and_writes_atomically(self, tmp_path, monkeypatch):
        new = tmp_path / "does" / "not" / "exist" / "access_requests.json"
        monkeypatch.setattr(access_requests, "DATA_FILE", new)
        monkeypatch.setattr(access_requests, "LEGACY_DATA_FILE", tmp_path / "none.json")
        access_requests.ensure_data_dir()
        assert new.parent.is_dir()
        access_requests.mutate(lambda reqs: reqs.append({"id": "0001"}))
        assert json.loads(new.read_text()) == [{"id": "0001"}]
        assert [p.name for p in new.parent.iterdir()] == ["access_requests.json"]  # no tmp left behind

    def test_ensure_data_dir_never_raises(self, monkeypatch):
        monkeypatch.setattr(access_requests, "DATA_FILE", Path("/proc/forbidden/dir/access_requests.json"))
        access_requests.ensure_data_dir()  # logged, not raised


# ── structural guard for the new router ──────────────────────────────────────


class TestDemoRouterGates:
    PUBLIC = {("POST", "/demo-access/code"), ("GET", "/demo-access/session")}

    @staticmethod
    def _requires_admin(route) -> bool:
        def walk(dep) -> bool:
            return dep.call is auth.require_admin or any(walk(d) for d in dep.dependencies)

        return walk(route.dependant)

    def test_every_non_public_route_requires_admin(self):
        seen = set()
        for route in demo_access.router.routes:
            for method in route.methods:
                key = (method, route.path.removeprefix("/api/v1"))
                seen.add(key)
                if key in self.PUBLIC:
                    assert not self._requires_admin(route)
                else:
                    assert self._requires_admin(route), f"{key} missing require_admin"
        assert seen >= self.PUBLIC
        assert len(seen - self.PUBLIC) == 2  # approve + provision retry

    def test_public_post_paths_are_exactly_the_two_forms(self):
        assert {"/api/v1/access-requests", "/api/v1/demo-access/code"} == auth.PUBLIC_POST_PATHS
