from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

from packages.common.schemas import (
    ConfidentialityTier,
    EventEnvelope,
    ExternalSignalEvent,
    InternalMilestoneEvent,
)
from packages.llm import LLMClient, LLMGateway, MockLLMClient, RedactionPolicy
from packages.taxonomy import Taxonomy
from services.matching.scorers import ScoringWeights

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Contact:
    contact_id: UUID
    contact_type: str
    name: str
    organization: str
    focus_areas: list[str]
    stated_thesis_tags: list[str]
    warm_signal_score: int
    under_nda: bool
    source_provenance: dict[str, str]
    disinterest_flag: bool = False
    last_contact_from_us_date: str | None = None
    active_conversation_token: str | None = None


@dataclass(frozen=True)
class MatchResult:
    candidate_id: UUID
    contact: Contact
    match_score: float
    match_rationale: str
    suppressed_reason: str | None = None


class MatchingEngine:
    def __init__(
        self,
        taxonomy: Taxonomy,
        contacts: list[Contact],
        weights: ScoringWeights | None = None,
        rollup_sub_institutes: bool = True,
        rationale_llm: LLMClient | None = None,
        bus=None,
    ) -> None:
        self.taxonomy = taxonomy
        self.contacts = contacts
        self.weights = weights or ScoringWeights()
        self.rollup_sub_institutes = rollup_sub_institutes
        self.rationale_llm = rationale_llm or MockLLMClient()
        # All LLM calls go through the gateway so redaction is enforced at one
        # gate rather than being the responsibility of each call site.
        self._gateway = LLMGateway(self.rationale_llm, RedactionPolicy())
        self.bus = bus  # optional – publishes outreach_candidate.* events when set

    def match_external_signal(self, event: ExternalSignalEvent) -> list[MatchResult]:
        event_institutes = [item.institute_id for item in event.institutes]
        if all(self.taxonomy.is_resolve_pending(institute_id) for institute_id in event_institutes):
            return [
                self._suppressed(contact, "taxonomy_resolve_pending") for contact in self.contacts[:1]
            ]
        return self._rank(
            event.event_id,
            event_institutes,
            event.topics,
            event_dict=event.model_dump(mode="json"),
            tier=ConfidentialityTier.PUBLIC,
        )

    def match_internal_milestone(self, event: InternalMilestoneEvent) -> list[MatchResult]:
        if event.confidentiality_tier == ConfidentialityTier.INTERNAL_ONLY:
            return []
        if self.taxonomy.is_resolve_pending(event.institute_id):
            return [self._suppressed(self.contacts[0], "taxonomy_resolve_pending")]

        contacts = self.contacts
        if event.confidentiality_tier == ConfidentialityTier.INVESTOR_NDA:
            contacts = [contact for contact in contacts if contact.under_nda]
        return self._rank(
            event.event_id,
            [event.institute_id],
            [],
            contacts=contacts,
            event_dict=event.model_dump(mode="json"),
            tier=event.confidentiality_tier,
        )

    def _rank(
        self,
        triggering_event_id: UUID,
        event_institutes: list[str],
        topics: list[str],
        contacts: list[Contact] | None = None,
        event_dict: dict | None = None,
        tier: ConfidentialityTier = ConfidentialityTier.PUBLIC,
    ) -> list[MatchResult]:
        active_contacts = contacts if contacts is not None else self.contacts
        results: list[MatchResult] = []
        for contact in active_contacts:
            suppression = self._suppression_reason(contact)
            if suppression:
                results.append(self._suppressed(contact, suppression))
                continue
            score = self._score(contact, event_institutes, topics)
            if score > 0:
                results.append(
                    MatchResult(
                        candidate_id=uuid4(),
                        contact=contact,
                        match_score=score,
                        match_rationale=self._write_rationale(
                            contact,
                            triggering_event_id,
                            event_institutes,
                            topics,
                            event_dict=event_dict,
                            tier=tier,
                        ),
                    )
                )
        ranked = sorted(results, key=lambda item: item.match_score, reverse=True)
        if self.bus:
            from packages.common.hashing import canonical_json, sha256_hex
            from packages.common.schemas import OutreachCandidateEvent

            for result in ranked:
                topic = (
                    "outreach_candidate.suppressed"
                    if result.suppressed_reason
                    else "outreach_candidate.created"
                )
                try:
                    candidate = OutreachCandidateEvent(
                        candidate_id=result.candidate_id,
                        contact_id=result.contact.contact_id,
                        triggering_event_id=triggering_event_id,
                        match_score=result.match_score,
                        match_rationale=result.match_rationale,
                        suggested_message_angle="",
                        suggested_channel="email",
                        confidence=min(max(result.match_score, 0.0), 1.0),
                    )
                    payload = candidate.model_dump(mode="json")
                    if result.suppressed_reason:
                        payload["suppressed_reason"] = result.suppressed_reason
                    self.bus.publish(
                        EventEnvelope(
                            event_id=result.candidate_id,
                            topic=topic,
                            payload=payload,
                            provenance_hash=sha256_hex(canonical_json(payload)),
                        )
                    )
                except Exception as exc:
                    logger.warning("Bus publish failed for %s: %s", topic, exc)
        return ranked

    def _score(self, contact: Contact, event_institutes: list[str], topics: list[str]) -> float:
        from services.matching.scorers import get_scorer
        scorer = get_scorer(contact.contact_type)
        return scorer.score(
            contact,
            event_institutes,
            topics,
            self.taxonomy,
            rollup=self.rollup_sub_institutes,
            weights=self.weights,
        )

    def _suppression_reason(self, contact: Contact) -> str | None:
        if contact.disinterest_flag:
            return "contact_disinterest"
        # Token bypass: a valid (non-expired) active_conversation_token skips cooldown
        from packages.hitl.conversation_token import is_token_valid
        if contact.last_contact_from_us_date and not is_token_valid(contact.active_conversation_token):
            last_contact = date.fromisoformat(contact.last_contact_from_us_date)
            if date.today() - last_contact < timedelta(days=60):
                return "cooldown_60_days"
        return None

    def _suppressed(self, contact: Contact, reason: str) -> MatchResult:
        return MatchResult(
            candidate_id=uuid4(),
            contact=contact,
            match_score=0,
            match_rationale="suppressed",
            suppressed_reason=reason,
        )

    def _write_rationale(
        self,
        contact: Contact,
        triggering_event_id: UUID,
        event_institutes: list[str],
        topics: list[str],
        event_dict: dict | None = None,
        tier: ConfidentialityTier = ConfidentialityTier.PUBLIC,
    ) -> str:
        if tier == ConfidentialityTier.INTERNAL_ONLY:
            # Should be filtered upstream; defensive guard.
            return "INTERNAL_ONLY content – rationale suppressed"

        def _build(safe: dict) -> str:
            return (
                "Write a short plain-English rationale explaining why this contact may be relevant. "
                "Do not change the deterministic ranking score.\n"
                f"Event ID: {triggering_event_id}\n"
                f"Event institutes: {', '.join(event_institutes)}\n"
                f"Event topics: {', '.join(topics)}\n"
                f"Contact: {contact.name}, {contact.organization}\n"
                f"Contact focus areas: {', '.join(contact.focus_areas)}\n"
                f"Contact thesis tags: {', '.join(contact.stated_thesis_tags)}\n"
                f"Signal summary: {safe.get('parsed_summary', safe.get('summary', ''))}"
            )

        response = self._gateway.complete_redacted(_build, event_dict or {}, tier=tier)
        return response.text.removeprefix("Mock response: ").strip()

