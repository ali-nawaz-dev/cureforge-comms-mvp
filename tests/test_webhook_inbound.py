"""Tests for the Resend inbound webhook handler.

Exercises the POST /webhook route against mocked Resend inbound payloads.
No live Resend connection required — Amine's MX change is still in progress.
Once inbound routing is verified, replace mock payloads with live-fire tests.

Webhook spec:
  POST /webhook
  Signature: HMAC-SHA256 of request body, header: Resend-Signature: sha256=<hex>
  Payload: standard Resend inbound email event JSON
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from services.outreach.webhook import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Mocked Resend inbound payload (representative of live format)
# ---------------------------------------------------------------------------

MOCK_INBOUND_PAYLOAD = {
    "type": "email.received",
    "data": {
        "from": "researcher@university.edu",
        "from_name": "Dr. Jane Smith",
        "to": ["replies@contact.longevityintime.org"],
        "subject": "Re: Longevity research collaboration",
        "text": "Thank you for reaching out. I'd love to schedule a meeting to discuss further.",
        "html": "<p>Thank you for reaching out. I'd love to schedule a meeting to discuss further.</p>",
        "candidate_id": "a1b2c3d4-0000-0000-0000-000000000001",
    },
}

MOCK_NOT_INTERESTED_PAYLOAD = {
    "type": "email.received",
    "data": {
        "from": "investor@fund.com",
        "from_name": "John Investor",
        "to": ["replies@contact.longevityintime.org"],
        "subject": "Re: Partnership opportunity",
        "text": "Thanks but I'm not interested at this time.",
        "html": "<p>Thanks but I'm not interested at this time.</p>",
        "candidate_id": "a1b2c3d4-0000-0000-0000-000000000002",
    },
}

MOCK_NEEDS_REVIEW_PAYLOAD = {
    "type": "email.received",
    "data": {
        "from": "contact@partner.org",
        "to": ["replies@contact.longevityintime.org"],
        "subject": "Re: Data use agreement",
        "text": "Could you send me more details about the data access requirements?",
        "candidate_id": "a1b2c3d4-0000-0000-0000-000000000003",
    },
}


def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()  # type: ignore[attr-defined]
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_webhook_meeting_requested_intent() -> None:
    """meeting_requested intent is classified correctly from a mocked payload."""
    body = json.dumps(MOCK_INBOUND_PAYLOAD).encode()
    response = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "meeting_requested"
    assert data["status"] == "ok"


def test_webhook_not_interested_intent() -> None:
    body = json.dumps(MOCK_NOT_INTERESTED_PAYLOAD).encode()
    response = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["intent"] == "not_interested"


def test_webhook_needs_review_intent() -> None:
    body = json.dumps(MOCK_NEEDS_REVIEW_PAYLOAD).encode()
    response = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["intent"] == "needs_review"


def test_webhook_hmac_signature_accepted(monkeypatch) -> None:
    """Valid HMAC-SHA256 signature passes verification."""
    secret = "test-webhook-secret-123"
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    body = json.dumps(MOCK_INBOUND_PAYLOAD).encode()
    sig = _make_signature(body, secret)
    response = client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "Resend-Signature": sig},
    )
    assert response.status_code == 200


def test_webhook_invalid_signature_rejected(monkeypatch) -> None:
    """Invalid HMAC signature returns 401."""
    secret = "correct-secret"
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    body = json.dumps(MOCK_INBOUND_PAYLOAD).encode()
    response = client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "Resend-Signature": "sha256=badhex"},
    )
    assert response.status_code == 401


def test_webhook_missing_signature_rejected_when_secret_set(monkeypatch) -> None:
    """Missing signature returns 401 when webhook secret is configured."""
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "some-secret")
    body = json.dumps(MOCK_INBOUND_PAYLOAD).encode()
    response = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 401


def test_webhook_no_secret_skips_verification() -> None:
    """When RESEND_WEBHOOK_SECRET is not set, signature check is skipped."""
    body = json.dumps(MOCK_INBOUND_PAYLOAD).encode()
    response = client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_webhook_invalid_json_returns_400() -> None:
    response = client.post(
        "/webhook", content=b"not valid json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
