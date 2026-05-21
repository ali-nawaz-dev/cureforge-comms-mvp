"""Tier-aware redaction for any payload that may reach an LLM.

The matching engine, drafting service, and any other LLM caller must run a
payload through ``redact_for_llm`` before the payload's fields end up in a
prompt. The set of fields we strip for INVESTOR_NDA is intentionally broad:
title, raw_text, parsed_summary, summary, narrative, and evidence refs.

INTERNAL_ONLY content must never reach an LLM – the function raises.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from packages.common.schemas import ConfidentialityTier


_NDA_REDACTED_FIELDS = (
    "summary",
    "narrative_for_outreach",
    "title",
    "raw_text",
    "parsed_summary",
    "match_rationale",
)

_NDA_CLEARED_LIST_FIELDS = ("supporting_evidence_refs",)


def redact_for_llm(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``event`` with tier-appropriate fields stripped.

    INTERNAL_ONLY raises – callers should branch on the tier *before* deciding
    to call an LLM at all rather than relying on this function to silently
    drop sensitive content.
    """
    if not event:
        return {}
    redacted = deepcopy(event)
    tier = redacted.get("confidentiality_tier")
    if tier == ConfidentialityTier.INTERNAL_ONLY.value:
        raise PermissionError(
            "INTERNAL_ONLY content cannot be sent to an LLM – callers must "
            "filter on confidentiality_tier before invoking the gateway"
        )
    if tier == ConfidentialityTier.INVESTOR_NDA.value:
        for field in _NDA_REDACTED_FIELDS:
            if field in redacted:
                redacted[field] = "[REDACTED_INVESTOR_NDA]"
        for field in _NDA_CLEARED_LIST_FIELDS:
            if field in redacted:
                redacted[field] = []
    return redacted
