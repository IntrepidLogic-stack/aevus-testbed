"""
Aevus -- signed, expiring, single-use approve tokens for the free-mail gate.

A token is ``base64url(payload).base64url(HMAC-SHA256(key, payload))`` where the
payload carries the request id, a random nonce, and an absolute expiry. Three
properties together make the link safe to email:

* Signed: HMAC with a server-held key (``ACCESS_APPROVE_SIGNING_KEY``). A
  tampered payload or a token minted without the key fails verification.
* Short-lived: ``exp`` is checked on every verify.
* Single-use: only ``sha256(nonce)`` is stored on the access-request record. The
  approve endpoint consumes it atomically (clears the hash) before provisioning,
  so a second click, a replay, or a link-scanner re-fetch cannot approve twice.

The token only *identifies* the pending request. Authority to approve still comes
from the admin-gated endpoint (``require_admin``); holding the token alone does
nothing. The key never lives in the repo and the module fails closed without it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

MIN_KEY_LEN = 32
_VERSION = 1


class ApproveTokenError(Exception):
    """Base class for any token failure. The message is safe to log, not to show."""


class ApproveKeyMissingError(ApproveTokenError):
    """No usable signing key is configured (fail closed)."""


class ApproveTokenInvalidError(ApproveTokenError):
    """Malformed token or bad signature."""


class ApproveTokenExpiredError(ApproveTokenError):
    """Signature is valid but the token is past its expiry."""


@dataclass(frozen=True)
class ApproveClaims:
    """Verified contents of an approve token."""

    request_id: str
    nonce: str
    expires_at: int


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key(signing_key: str) -> bytes:
    if not signing_key or len(signing_key) < MIN_KEY_LEN:
        raise ApproveKeyMissingError(f"ACCESS_APPROVE_SIGNING_KEY must be set and at least {MIN_KEY_LEN} characters")
    return signing_key.encode("utf-8")


def _sign(payload_b64: str, signing_key: str) -> str:
    return _b64e(hmac.new(_key(signing_key), payload_b64.encode("ascii"), hashlib.sha256).digest())


def hash_nonce(nonce: str) -> str:
    """SHA-256 hex of a nonce; this (not the nonce) is what the store keeps."""
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def issue_token(request_id: str, signing_key: str, ttl_seconds: int, *, now: float | None = None) -> tuple[str, str]:
    """Mint a token. Returns ``(token, nonce_sha256)``; persist only the hash."""
    nonce = secrets.token_urlsafe(24)
    exp = int((time.time() if now is None else now) + ttl_seconds)
    payload = json.dumps({"v": _VERSION, "rid": request_id, "n": nonce, "exp": exp}, separators=(",", ":"))
    payload_b64 = _b64e(payload.encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64, signing_key)}", hash_nonce(nonce)


def verify_token(token: str, signing_key: str, *, now: float | None = None) -> ApproveClaims:
    """Verify signature and expiry. Raises an ApproveTokenError subclass on failure.

    This does NOT check single-use; the caller must compare ``hash_nonce(nonce)``
    against the stored hash and clear it under the store lock.
    """
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 1024:
        raise ApproveTokenInvalidError("malformed token")
    payload_b64, sig = token.split(".")
    expected = _sign(payload_b64, signing_key)  # raises ApproveKeyMissingError without a key
    if not hmac.compare_digest(sig, expected):
        raise ApproveTokenInvalidError("bad signature")
    try:
        data = json.loads(_b64d(payload_b64))
        if data.get("v") != _VERSION:
            raise ValueError("version")
        claims = ApproveClaims(request_id=str(data["rid"]), nonce=str(data["n"]), expires_at=int(data["exp"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise ApproveTokenInvalidError("malformed payload") from exc
    if (time.time() if now is None else now) >= claims.expires_at:
        raise ApproveTokenExpiredError("token expired")
    return claims
