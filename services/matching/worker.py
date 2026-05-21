"""MatcherWorker: subscribes to ``external_signal.*`` and publishes
validated ``OutreachCandidateEvent`` envelopes.

Before this worker existed, the matching engine was always called
imperatively from the dashboard/tests, and any candidate publishes were a
side effect of the engine's ``bus=`` parameter. With the worker the bus
becomes the real spine: producers publish a signal, the worker subscribes
and runs matching, and downstream consumers (outreach, ledger) only need
to know about the bus.

Failures: any uncaught exception is republished to ``dlq.external_signal``
with the original envelope plus ``{"error": "..."}`` so issues can be
inspected without taking the matcher offline.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from packages.bus import DLQ_PREFIX, MessageBus
from packages.bus.idempotency import IdempotencyCache
from packages.common.hashing import canonical_json, sha256_hex
from packages.common.schemas import (
    EventEnvelope,
    ExternalSignalEvent,
    OutreachCandidateEvent,
)
from services.matching.engine import MatchingEngine, MatchResult

logger = logging.getLogger(__name__)

CANDIDATE_TOPIC = "outreach_candidate.created"
SUPPRESSED_TOPIC = "outreach_candidate.suppressed"


class MatcherWorker:
    def __init__(
        self,
        bus: MessageBus,
        engine: MatchingEngine,
        *,
        ledger: Any | None = None,
    ) -> None:
        self._bus = bus
        self._engine = engine
        self._ledger = ledger
        self._idempotency = IdempotencyCache()

    def start(self) -> None:
        self._bus.subscribe("external_signal.*", self._handle)

    def _handle(self, envelope: EventEnvelope) -> None:
        if not self._idempotency.claim(str(envelope.event_id)):
            return
        try:
            event = ExternalSignalEvent.model_validate(envelope.payload)
        except Exception as exc:
            self._publish_dlq(envelope, f"invalid_external_signal: {exc}")
            return
        try:
            results = self._engine.match_external_signal(event)
        except Exception as exc:
            logger.exception("MatcherWorker engine error")
            self._publish_dlq(envelope, f"engine_error: {exc}")
            return

        for result in results:
            try:
                self._publish_result(result, event)
            except Exception as exc:
                logger.exception("MatcherWorker publish error")
                self._publish_dlq(envelope, f"publish_error: {exc}")

        if self._ledger:
            try:
                self._ledger.append(
                    "matching_run",
                    {
                        "triggering_event_id": str(event.event_id),
                        "candidate_count": len(results),
                    },
                )
            except Exception as exc:
                logger.warning("MatcherWorker ledger append failed: %s", exc)

    def _publish_result(
        self, result: MatchResult, source_event: ExternalSignalEvent
    ) -> None:
        topic = SUPPRESSED_TOPIC if result.suppressed_reason else CANDIDATE_TOPIC
        candidate = OutreachCandidateEvent(
            candidate_id=result.candidate_id,
            contact_id=_to_uuid(result.contact.contact_id),
            triggering_event_id=source_event.event_id,
            match_score=result.match_score,
            match_rationale=result.match_rationale,
            suggested_message_angle="",
            suggested_channel="email",
            confidence=min(max(result.match_score, 0.0), 1.0),
        )
        payload = candidate.model_dump(mode="json")
        if result.suppressed_reason:
            payload["suppressed_reason"] = result.suppressed_reason
        provenance = sha256_hex(canonical_json(payload))
        envelope = EventEnvelope(
            event_id=result.candidate_id,
            topic=topic,
            payload=payload,
            provenance_hash=provenance,
        )
        self._bus.publish(envelope)

    def _publish_dlq(self, envelope: EventEnvelope, error: str) -> None:
        try:
            payload = {
                "original_topic": envelope.topic,
                "original_event_id": str(envelope.event_id),
                "original_payload": envelope.payload,
                "error": error,
            }
            self._bus.publish(
                EventEnvelope(
                    event_id=uuid4(),
                    topic=f"{DLQ_PREFIX}external_signal",
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
