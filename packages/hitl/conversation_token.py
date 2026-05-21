"""Active-conversation token manager.

Rules:
- Layer 3A issues a token when an inbound reply with intent ∈
  {interested, needs_info, meeting_requested, needs_review} arrives.
- TTL: 30 days from issuance.
- Refreshes on each new reply.
- Revoked immediately on intent == not_interested.
- A valid token lets matching/sending bypass the 60-day outreach cooldown.

Token format
------------
``<b64url(payload_json)>.<b64url(hmac_sha256(payload_json, secret))>``

where ``payload_json`` is ``{"contact_id": "...", "exp": "<iso UTC>"}``.

Compared to the previous ``<contact_id>:<expires>`` format this:

- Uses HMAC-SHA256 over a server secret so tokens cannot be forged.
- Carries an explicit, UTC-anchored expiry – no timezone surprises.
- Survives ``contact_id`` values that contain ``:`` (e.g. some external
  identifiers).
- ``is_token_valid`` rejects any token whose signature or payload no longer
  matches.

The secret is read from ``CONVERSATION_TOKEN_SECRET``. A dev default is
used when the env var is unset so local tests work without configuration.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_ACTIVE_INTENTS = {"interested", "needs_info", "meeting_requested", "needs_review"}
_REVOKE_INTENTS = {"not_interested"}
_TOKEN_TTL_DAYS = 30
_DEV_SECRET = "dev-conversation-token-secret-do-not-use-in-prod"


def _secret() -> bytes:
    return os.getenv("CONVERSATION_TOKEN_SECRET", _DEV_SECRET).encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload_bytes: bytes) -> str:
    digest = hmac.new(_secret(), payload_bytes, hashlib.sha256).digest()
    return _b64url(digest)


def should_issue_token(intent: str) -> bool:
    return intent in _ACTIVE_INTENTS


def should_revoke_token(intent: str) -> bool:
    return intent in _REVOKE_INTENTS


def issue_token(contact_id: str, *, ttl_days: int = _TOKEN_TTL_DAYS) -> str:
    """Issue a fresh signed token for ``contact_id``."""
    if not contact_id:
        raise ValueError("contact_id must be non-empty")
    exp = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
    payload = {"contact_id": str(contact_id), "exp": exp}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = f"{_b64url(payload_bytes)}.{_sign(payload_bytes)}"
    logger.info(
        "Active-conversation token issued",
        extra={"contact_id": contact_id, "expires_at": exp},
    )
    return token


def parse_token(token: str | None) -> dict | None:
    """Return the verified payload dict, or ``None`` if the token is invalid."""
    if not token or not isinstance(token, str) or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        expected = _sign(payload_bytes)
        if not hmac.compare_digest(expected, sig_b64):
            return None
        return json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def is_token_valid(token: str | None) -> bool:
    payload = parse_token(token)
    if not payload:
        return False
    try:
        exp = datetime.fromisoformat(payload["exp"])
    except (KeyError, ValueError):
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) <= exp


def token_expiry(token: str | None) -> str | None:
    payload = parse_token(token)
    if not payload:
        return None
    return payload.get("exp")


def token_contact_id(token: str | None) -> str | None:
    payload = parse_token(token)
    if not payload:
        return None
    return payload.get("contact_id")


def handle_reply_token(
    contact_id: str,
    intent: str,
    current_token: str | None,
) -> str | None:
    """Apply token lifecycle rules based on reply intent."""
    if should_revoke_token(intent):
        if current_token:
            logger.info(
                "Active-conversation token revoked (not_interested)",
                extra={"contact_id": contact_id},
            )
        return None
    if should_issue_token(intent):
        return issue_token(contact_id)
    return current_token
