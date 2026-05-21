"""LLMGateway — enforced redaction boundary in front of every LLM call.

Before this gateway existed, ``redacted`` on ``LLMResponse`` was advisory.
Callers could call ``client.complete(prompt)`` with raw NDA content and the
flag would simply be False on the response. That made the redaction layer
trivially bypassable.

The gateway:
- Wraps any object implementing the LLMClient protocol.
- Takes a ``RedactionPolicy`` that decides which fields are safe per tier.
- Refuses to send a prompt unless the caller asserted ``redacted=True``
  and the prompt is free of NDA markers.

Callers that genuinely want to use a tier-redacted dict should call
``gateway.complete_redacted(prompt_builder, payload, tier=...)`` which runs
the redaction step *inside* the gateway, eliminating "did the caller
redact?" ambiguity.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from packages.common.schemas import ConfidentialityTier
from packages.llm.client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

# Markers that should never reach an LLM verbatim. The list is kept short
# and explicit – the gateway must be cheap.
_NDA_MARKERS = (
    "[INVESTOR_NDA]",
    "INVESTOR_NDA:",
    "[INTERNAL_ONLY]",
    "INTERNAL_ONLY:",
)


class RedactionPolicyError(RuntimeError):
    """Raised when a prompt fails the gateway's redaction policy."""


class RedactionPolicy:
    """Tier-aware payload sanitizer."""

    #: Fields stripped to a placeholder for INVESTOR_NDA content.
    NDA_REDACTED_FIELDS = (
        "summary",
        "narrative_for_outreach",
        "title",
        "raw_text",
        "parsed_summary",
        "match_rationale",
    )

    NDA_CLEARED_LIST_FIELDS = ("supporting_evidence_refs",)

    def redact(self, payload: dict[str, Any], tier: ConfidentialityTier) -> dict[str, Any]:
        from copy import deepcopy

        clean = deepcopy(payload)
        if tier == ConfidentialityTier.INTERNAL_ONLY:
            # INTERNAL_ONLY content must never leave the system at all.
            raise RedactionPolicyError(
                "INTERNAL_ONLY content cannot be sent to an LLM"
            )
        if tier == ConfidentialityTier.INVESTOR_NDA:
            for field in self.NDA_REDACTED_FIELDS:
                if field in clean:
                    clean[field] = "[REDACTED_INVESTOR_NDA]"
            for field in self.NDA_CLEARED_LIST_FIELDS:
                if field in clean:
                    clean[field] = []
        return clean

    def assert_safe(self, prompt: str) -> None:
        """Raise if the prompt contains a known NDA marker.

        This is a belt-and-suspenders check – the structured ``redact()``
        path should already have stripped these. Catching them here means a
        caller who hand-rolls a prompt cannot accidentally leak.
        """
        for marker in _NDA_MARKERS:
            if marker in prompt:
                raise RedactionPolicyError(
                    f"Prompt contains NDA marker {marker!r} – refusing to send"
                )
        # Crude PII regex check: long sequences of credit-card-looking digits.
        if re.search(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", prompt):
            raise RedactionPolicyError("Prompt contains suspected card number")


class LLMGateway:
    """Enforced redaction wrapper around an LLMClient."""

    def __init__(
        self,
        client: LLMClient,
        policy: RedactionPolicy | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or RedactionPolicy()

    @property
    def provider(self) -> str:
        return getattr(self._client, "provider", "unknown")

    @property
    def model(self) -> str:
        return getattr(self._client, "model", "unknown")

    def complete(
        self, prompt: str, *, redacted: bool, tier: ConfidentialityTier | None = None
    ) -> LLMResponse:
        """Send ``prompt`` to the underlying client after policy checks.

        ``redacted=True`` must be asserted explicitly by the caller. The
        gateway also runs a marker scan as a second line of defence.
        """
        if not redacted:
            raise RedactionPolicyError(
                "LLMGateway requires the caller to assert redacted=True"
            )
        if tier == ConfidentialityTier.INTERNAL_ONLY:
            raise RedactionPolicyError(
                "INTERNAL_ONLY content cannot be sent to an LLM"
            )
        self._policy.assert_safe(prompt)
        return self._client.complete(prompt, redacted=True)

    def complete_redacted(
        self,
        prompt_builder: Callable[[dict[str, Any]], str],
        payload: dict[str, Any],
        *,
        tier: ConfidentialityTier = ConfidentialityTier.PUBLIC,
    ) -> LLMResponse:
        """Redact ``payload`` per ``tier`` then build the prompt and send.

        This is the safer entry point: prompt construction sees only the
        sanitized payload, so callers cannot inadvertently leak the raw
        field they forgot to redact.
        """
        sanitized = self._policy.redact(payload, tier)
        prompt = prompt_builder(sanitized)
        return self.complete(prompt, redacted=True, tier=tier)
