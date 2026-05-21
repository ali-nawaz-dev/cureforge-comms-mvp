"""Phase 2 security tests for LLM gateway, conversation token, and webhook."""
from __future__ import annotations

import json

import pytest

from packages.common.schemas import ConfidentialityTier
from packages.llm import (
    LLMConfigError,
    LLMGateway,
    MockLLMClient,
    RedactionPolicy,
    RedactionPolicyError,
)
from packages.llm.http_clients import GroqLLMClient, OpenAILLMClient


def test_gateway_refuses_when_caller_does_not_assert_redacted() -> None:
    gw = LLMGateway(MockLLMClient(), RedactionPolicy())
    with pytest.raises(RedactionPolicyError):
        gw.complete("Hello", redacted=False)


def test_gateway_refuses_prompts_with_nda_markers() -> None:
    gw = LLMGateway(MockLLMClient(), RedactionPolicy())
    with pytest.raises(RedactionPolicyError):
        gw.complete("[INVESTOR_NDA] secret content", redacted=True)


def test_gateway_refuses_internal_only_payloads() -> None:
    gw = LLMGateway(MockLLMClient(), RedactionPolicy())
    with pytest.raises(RedactionPolicyError):
        gw.complete_redacted(
            lambda safe: "anything",
            {"summary": "very secret"},
            tier=ConfidentialityTier.INTERNAL_ONLY,
        )


def test_gateway_redacts_nda_fields_before_prompt() -> None:
    gw = LLMGateway(MockLLMClient(), RedactionPolicy())
    captured: dict = {}

    def build(safe: dict) -> str:
        captured.update(safe)
        return "x"

    gw.complete_redacted(
        build,
        {
            "summary": "secret",
            "narrative_for_outreach": "secret",
            "title": "secret title",
            "match_rationale": "secret rationale",
            "confidentiality_tier": ConfidentialityTier.INVESTOR_NDA.value,
        },
        tier=ConfidentialityTier.INVESTOR_NDA,
    )

    assert captured["summary"] == "[REDACTED_INVESTOR_NDA]"
    assert captured["narrative_for_outreach"] == "[REDACTED_INVESTOR_NDA]"
    assert captured["title"] == "[REDACTED_INVESTOR_NDA]"
    assert captured["match_rationale"] == "[REDACTED_INVESTOR_NDA]"


def test_groq_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        GroqLLMClient(api_key="")


def test_openai_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        OpenAILLMClient(api_key="")


def test_webhook_fails_closed_in_production(monkeypatch) -> None:
    """Outside local/test/dev the webhook must refuse to verify-skip."""
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    from fastapi.testclient import TestClient
    from services.outreach.webhook import app

    client = TestClient(app)
    body = json.dumps({"type": "email.received", "data": {"text": "Hi"}}).encode()
    response = client.post(
        "/webhook", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 503


def test_webhook_replay_dedup(monkeypatch) -> None:
    """Same svix-id event is acknowledged but treated as duplicate."""
    import time
    import base64
    import hashlib
    import hmac as stdlib_hmac

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_" + base64.b64encode(b"secret").decode())

    from fastapi.testclient import TestClient
    from services.outreach.webhook import app, _DEDUP_LRU

    _DEDUP_LRU.clear()
    client = TestClient(app)
    body = json.dumps(
        {"type": "email.received", "data": {"text": "Hi", "from": "x@y.com"}}
    ).encode()
    svix_id = "msg_test_1"
    svix_ts = str(int(time.time()))

    payload = f"{svix_id}.{svix_ts}.".encode() + body
    sig = base64.b64encode(
        stdlib_hmac.new(b"secret", payload, hashlib.sha256).digest()
    ).decode()
    headers = {
        "Content-Type": "application/json",
        "svix-id": svix_id,
        "svix-timestamp": svix_ts,
        "svix-signature": f"v1,{sig}",
    }

    first = client.post("/webhook", content=body, headers=headers)
    second = client.post("/webhook", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
