"""OutreachWorker: subscribes to ``outreach_candidate.created`` and writes
drafts into the HITL approval queue.

Drafting still goes through the ``LLMGateway`` so contact data is redacted
per tier (``LLMGateway`` is wired inside ``OutreachDraftingService``).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from packages.bus import DLQ_PREFIX, MessageBus
from packages.bus.idempotency import IdempotencyCache
from packages.common.hashing import canonical_json, sha256_hex
from packages.common.schemas import EventEnvelope, OutreachCandidateEvent
from packages.hitl import ApprovalQueue
from services.matching.engine import Contact, MatchResult
from services.outreach.drafting import OutreachDraftingService

logger = logging.getLogger(__name__)

DRAFT_TOPIC = "outreach_draft.created"


class OutreachWorker:
    def __init__(
        self,
        bus: MessageBus,
        queue: ApprovalQueue,
        contacts: list[Contact],
        *,
        drafting_service: OutreachDraftingService | None = None,
        required_roles: set[str] | None = None,
        ledger: Any | None = None,
    ) -> None:
        self._bus = bus
        self._queue = queue
        self._contacts = {str(c.contact_id): c for c in contacts}
        self._drafting = drafting_service or OutreachDraftingService()
        self._required_roles = required_roles or {"principal_investigator"}
        self._ledger = ledger
        self._idempotency = IdempotencyCache()

    def start(self) -> None:
        self._bus.subscribe("outreach_candidate.created", self._handle)

    def _handle(self, envelope: EventEnvelope) -> None:
        if not self._idempotency.claim(str(envelope.event_id)):
            return
        try:
            candidate = OutreachCandidateEvent.model_validate(envelope.payload)
        except Exception as exc:
            self._publish_dlq(envelope, f"invalid_candidate: {exc}")
            return
        contact = self._contacts.get(str(candidate.contact_id))
        if not contact:
            self._publish_dlq(envelope, f"unknown_contact:{candidate.contact_id}")
            return

        match = MatchResult(
            candidate_id=candidate.candidate_id,
            contact=contact,
            match_score=candidate.match_score,
            match_rationale=candidate.match_rationale,
        )
        try:
            body = self._drafting.draft_email(match)
        except Exception as exc:
            logger.exception("Drafting failed")
            self._publish_dlq(envelope, f"drafting_error: {exc}")
            return

        record = self._queue.draft(body, self._required_roles)
        if self._ledger:
            try:
                self._ledger.append(
                    "outreach_draft",
                    {
                        "candidate_id": str(candidate.candidate_id),
                        "draft_id": str(record.draft_id),
                    },
                )
            except Exception as exc:
                logger.warning("OutreachWorker ledger append failed: %s", exc)

        payload = {
            "draft_id": str(record.draft_id),
            "candidate_id": str(candidate.candidate_id),
            "contact_id": str(candidate.contact_id),
        }
        self._bus.publish(
            EventEnvelope(
                event_id=record.draft_id,
                topic=DRAFT_TOPIC,
                payload=payload,
                provenance_hash=sha256_hex(canonical_json(payload)),
            )
        )

    def _publish_dlq(self, envelope: EventEnvelope, error: str) -> None:
        payload = {
            "original_topic": envelope.topic,
            "original_event_id": str(envelope.event_id),
            "original_payload": envelope.payload,
            "error": error,
        }
        try:
            self._bus.publish(
                EventEnvelope(
                    event_id=uuid4(),
                    topic=f"{DLQ_PREFIX}outreach_candidate",
                    payload=payload,
                    provenance_hash=sha256_hex(canonical_json(payload)),
                )
            )
        except Exception as exc:
            logger.error("DLQ publish failed: %s", exc)


def _to_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
