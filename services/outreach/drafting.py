"""Outreach drafting service.

Wraps any LLM client behind ``LLMGateway`` so that contact fields and the
match rationale are passed through ``RedactionPolicy`` before they reach
the model. Drafts always include an explicit "not yet sent" instruction,
and the gateway will refuse to call the LLM with INTERNAL_ONLY content.
"""
from __future__ import annotations

from packages.common.schemas import ConfidentialityTier
from packages.llm import LLMClient, LLMGateway, MockLLMClient, RedactionPolicy
from services.matching import MatchResult


class OutreachDraftingService:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        gateway: LLMGateway | None = None,
        policy: RedactionPolicy | None = None,
    ) -> None:
        self.llm_client = llm_client or MockLLMClient()
        self._gateway = gateway or LLMGateway(self.llm_client, policy or RedactionPolicy())

    def draft_email(
        self,
        match: MatchResult,
        *,
        tier: ConfidentialityTier = ConfidentialityTier.PUBLIC,
    ) -> str:
        payload = {
            "name": match.contact.name,
            "organization": match.contact.organization,
            "match_rationale": match.match_rationale,
            "confidentiality_tier": tier.value,
        }

        def _build(safe: dict) -> str:
            return (
                "Draft a concise outreach email for a human reviewer to approve. "
                "Do not claim the email has been sent.\n"
                f"Recipient: {safe['name']}\n"
                f"Organization: {safe['organization']}\n"
                f"Rationale: {safe.get('match_rationale', '')}"
            )

        response = self._gateway.complete_redacted(_build, payload, tier=tier)
        text = response.text.removeprefix("Mock response: ").strip()
        if "Hi " not in text:
            return (
                f"Hi {match.contact.name},\n\n"
                f"{text}\n\n"
                "Would you be open to a short conversation?\n\n"
                "Best,\nCureForge AI"
            )
        return text
