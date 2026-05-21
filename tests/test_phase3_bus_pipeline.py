"""End-to-end integration of the bus spine.

Publishes an ``external_signal.*`` envelope, asserts that:
- MatcherWorker emits a validated ``OutreachCandidateEvent``.
- OutreachWorker creates a HITL draft.
- Idempotency suppresses a duplicate redelivery.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from packages.bus import InMemoryBus
from packages.common.schemas import EventEnvelope, ExternalSignalEvent, InstituteClassification
from packages.hitl import ApprovalQueue
from packages.ledger.chain import Ledger
from packages.taxonomy import load_taxonomy
from services.matching import MatchingEngine
from services.matching.contacts import load_contacts
from services.matching.worker import MatcherWorker
from services.outreach.worker import OutreachWorker


def _make_envelope() -> EventEnvelope:
    event = ExternalSignalEvent(
        event_id=uuid4(),
        source="telegram",
        source_url="telegram://t",
        ingest_timestamp="2025-01-01T00:00:00Z",
        content_hash="a" * 64,
        parsed_summary="stem cell longevity update",
        institutes=[InstituteClassification(institute_id="48", confidence=0.9)],
        topics=["longevity"],
        raw_text_ref="raw:a",
        classifier_confidence=0.8,
        parser_confidence=0.8,
        provenance_hash="p",
    )
    return EventEnvelope(
        event_id=event.event_id,
        topic="external_signal.telegram.48",
        payload=event.model_dump(mode="json"),
    )


def test_bus_pipeline_end_to_end() -> None:
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    engine = MatchingEngine(taxonomy=taxonomy, contacts=contacts)
    queue = ApprovalQueue()
    ledger = Ledger()

    matcher = MatcherWorker(bus, engine, ledger=ledger)
    matcher.start()
    outreach = OutreachWorker(bus, queue, contacts, ledger=ledger)
    outreach.start()

    bus.publish(_make_envelope())

    candidate_topics = [e.topic for e in bus.published if e.topic.startswith("outreach_candidate.")]
    draft_topics = [e.topic for e in bus.published if e.topic == "outreach_draft.created"]
    assert candidate_topics, "MatcherWorker must publish outreach_candidate.* events"
    assert draft_topics, "OutreachWorker must publish outreach_draft.created events"
    assert any(record.state.value == "AWAITING_APPROVAL" for record in queue.records.values())


def test_matcher_worker_dedups_duplicate_envelopes() -> None:
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    engine = MatchingEngine(taxonomy=taxonomy, contacts=contacts)
    matcher = MatcherWorker(bus, engine)
    matcher.start()

    envelope = _make_envelope()
    bus.publish(envelope)
    candidates_after_first = sum(
        1 for e in bus.published if e.topic.startswith("outreach_candidate.")
    )
    bus.publish(envelope)
    candidates_after_second = sum(
        1 for e in bus.published if e.topic.startswith("outreach_candidate.")
    )
    assert candidates_after_second == candidates_after_first


def test_matcher_worker_routes_invalid_payload_to_dlq() -> None:
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    engine = MatchingEngine(taxonomy=taxonomy, contacts=[])
    matcher = MatcherWorker(bus, engine)
    matcher.start()

    bad = EventEnvelope(
        event_id=uuid4(),
        topic="external_signal.telegram.invalid",
        payload={"this": "is not a valid ExternalSignalEvent"},
    )
    bus.publish(bad)

    dlq = [e for e in bus.published if e.topic == "dlq.external_signal"]
    assert dlq, "Invalid external_signal payloads must be sent to dlq.external_signal"
    assert "invalid_external_signal" in json.dumps(dlq[0].payload)
