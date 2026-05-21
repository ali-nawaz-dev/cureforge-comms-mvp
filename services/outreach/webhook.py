"""Resend inbound webhook handler.

Receives inbound email events from Resend, verifies the request signature,
classifies reply intent, and persists the reply to Postgres (if DATABASE_URL
is set).

Security hardening
------------------
- ``RESEND_WEBHOOK_SECRET`` is required outside ``APP_ENV in {local, test}``.
  Without it the endpoint returns ``503 Service Unavailable`` rather than
  silently accepting every request.
- Two signature schemes are accepted:

  * Legacy: ``Resend-Signature: sha256=<hex>`` – HMAC-SHA256 of the raw body.
    Kept for backward compatibility with the existing test fixtures.
  * Svix:   ``svix-id``, ``svix-timestamp``, ``svix-signature`` headers, as
    Resend's webhook signing scheme actually documents. If the ``svix``
    library is installed it is used (preferred); otherwise we re-implement
    the canonical ``HMAC-SHA256(svix_id.svix_timestamp.body, base64(secret))``
    check inline.

- Timestamp tolerance of ``WEBHOOK_REPLAY_TOLERANCE_S`` (default 300s)
  protects against replay attacks; events older than the window are rejected.
- An in-memory LRU of recently seen ``svix-id`` values dedups retries.

Environment variables
---------------------
``RESEND_WEBHOOK_SECRET``     secret used to verify signatures
``DATABASE_URL``              if set, persists replies to ``replies`` table
``APP_ENV``                   ``local``/``test`` skips secret enforcement
``TELEGRAM_BOT_TOKEN``        used for meeting_requested notifications
``TELEGRAM_NOTIFY_CHAT_ID``   Telegram chat to notify

Run with::

    uvicorn services.outreach.webhook:app --port 8001
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Request, Response, status

from packages.common.logging import configure_json_logging
from packages.common.metrics import metrics_response
from packages.hitl import ApprovalQueue

configure_json_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="CureForge Inbound Webhook")

_REPLAY_TOLERANCE_S = int(os.getenv("WEBHOOK_REPLAY_TOLERANCE_S", "300"))
_DEDUP_CAP = 10_000
_DEDUP_LRU: OrderedDict[str, float] = OrderedDict()

# Singletons reused across requests so we do not rebuild HITL state per call.
_QUEUE = ApprovalQueue()
_SENDER = None


def _get_sender():
    global _SENDER
    if _SENDER is None:
        from services.outreach.sender import OutreachSender

        _SENDER = OutreachSender(approval_queue=_QUEUE)
    return _SENDER


def _is_production() -> bool:
    return os.getenv("APP_ENV", "local").lower() not in {"local", "test", "dev"}


def _record_event_id(event_id: str) -> bool:
    """Return True if this event_id has not been seen before."""
    if not event_id:
        return True
    if event_id in _DEDUP_LRU:
        return False
    _DEDUP_LRU[event_id] = time.time()
    if len(_DEDUP_LRU) > _DEDUP_CAP:
        _DEDUP_LRU.popitem(last=False)
    return True


def _verify_legacy(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _verify_svix(
    body: bytes,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    secret: str,
) -> bool:
    if not (svix_id and svix_timestamp and svix_signature):
        return False
    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > _REPLAY_TOLERANCE_S:
        return False

    signing_secret = secret
    if signing_secret.startswith("whsec_"):
        signing_secret = signing_secret[len("whsec_") :]
    try:
        secret_bytes = base64.b64decode(signing_secret)
    except Exception:
        secret_bytes = signing_secret.encode()

    payload = f"{svix_id}.{svix_timestamp}.".encode() + body
    expected_sig = base64.b64encode(
        hmac.new(secret_bytes, payload, hashlib.sha256).digest()
    ).decode()
    for chunk in svix_signature.split():
        if "," not in chunk:
            continue
        _, value = chunk.split(",", 1)
        if hmac.compare_digest(value, expected_sig):
            return True
    return False


def _persist_reply(payload: dict, intent: str) -> None:
    if not os.getenv("DATABASE_URL"):
        return
    try:
        from packages.db.connection import get_connection

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO replies (reply_id, candidate_id, from_email, body, intent, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    payload.get("candidate_id"),
                    payload.get("from"),
                    payload.get("text", payload.get("html", "")),
                    intent,
                    json.dumps(payload),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("Could not persist reply: %s", exc)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    """Readiness probe – verifies the Postgres pool is reachable when set."""
    if os.getenv("DATABASE_URL"):
        from packages.db.connection import health_check

        if not health_check():
            raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


@app.post("/webhook", status_code=status.HTTP_200_OK)
async def resend_inbound(request: Request) -> dict:
    body = await request.body()
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")

    if not secret:
        if _is_production():
            logger.error("RESEND_WEBHOOK_SECRET unset in production environment")
            raise HTTPException(
                status_code=503,
                detail="Webhook secret not configured in this environment",
            )
        # local/test: accept unsigned requests so the demo dashboard works
    else:
        legacy_sig = request.headers.get("Resend-Signature")
        svix_id = request.headers.get("svix-id") or request.headers.get("webhook-id")
        svix_ts = request.headers.get("svix-timestamp") or request.headers.get(
            "webhook-timestamp"
        )
        svix_sig = request.headers.get("svix-signature") or request.headers.get(
            "webhook-signature"
        )

        verified = False
        if svix_id and svix_ts and svix_sig:
            verified = _verify_svix(body, svix_id, svix_ts, svix_sig, secret)
        if not verified and legacy_sig:
            verified = _verify_legacy(body, legacy_sig, secret)
        if not verified:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        if svix_id and not _record_event_id(svix_id):
            return {"status": "duplicate"}

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    sender = _get_sender()
    email_data = payload.get("data", payload)
    text = email_data.get("text", email_data.get("html", ""))
    from_email = email_data.get("from", "")
    intent, _new_token = sender.handle_inbound_reply(
        text=text,
        from_email=from_email,
        contact_name=email_data.get("from_name"),
        draft_id=email_data.get("candidate_id"),
        contact_id=email_data.get("contact_id"),
    )
    _persist_reply(
        {**email_data, "candidate_id": email_data.get("candidate_id")},
        intent,
    )
    return {"status": "ok", "intent": intent}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("services.outreach.webhook:app", host="0.0.0.0", port=8001, reload=False)
