"""Regression tests for Phase 1 fixes."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from packages.bus import InMemoryBus
from packages.common.schemas import EventEnvelope
from packages.hitl import ApprovalQueue
from packages.hitl.queue import DraftNotFound
from packages.kg.stub import KnowledgeGraphStub
from packages.ledger.chain import Ledger
from packages.taxonomy import load_taxonomy
from services.ingestion.pipeline import IngestionPipeline, RawSignal
from services.ingestion.sources import clinical_trials_signal
from services.matching import Contact, MatchingEngine
from services.outreach.sender import OutreachSender


# --- Bus -------------------------------------------------------------------


def test_redis_bus_publish_does_not_double_dispatch_locally() -> None:
    """Local fan-out was removed from RedisBus.publish; the listener thread alone
    is responsible for invoking handlers. Without Redis available we can still
    assert the publish() body no longer calls _fan_out directly."""
    from packages.bus import redis_bus

    captured: list[str] = []

    class _FakeClient:
        def publish(self, topic: str, payload: str) -> None:
            captured.append(topic)

    class _FakePubSub:
        def psubscribe(self, **kwargs) -> None:
            pass

        def subscribe(self, **kwargs) -> None:
            pass

        def run_forever(self, sleep_time: float = 0.01) -> None:
            pass

        def close(self) -> None:
            pass

    from collections import defaultdict

    bus = object.__new__(redis_bus.RedisBus)
    bus._client = _FakeClient()
    bus._pubsub = _FakePubSub()
    bus._handlers = defaultdict(list)
    bus._listener_thread = None
    bus._started = False

    handler_calls: list[EventEnvelope] = []
    bus.subscribe("external_signal.*", handler_calls.append)

    envelope = EventEnvelope(
        event_id=uuid4(),
        topic="external_signal.telegram.13",
        payload={"hello": "world"},
    )
    bus.publish(envelope)
    bus.close()

    assert captured == ["external_signal.telegram.13"]
    assert handler_calls == []  # listener thread would deliver in real Redis


# --- Ingestion sources -----------------------------------------------------


def test_clinical_trials_signal_uses_canonical_source_string() -> None:
    signal = clinical_trials_signal("Longevity-tested compound")
    assert signal.source == "clinicaltrials_gov"
    assert "clinical_trial" in signal.topics


# --- Ledger ----------------------------------------------------------------


def test_ledger_record_ids_are_monotonic_and_chain_verifies() -> None:
    ledger = Ledger()
    a = ledger.append("signal", {"k": 1})
    b = ledger.append("signal", {"k": 2})
    assert b.record_id == a.record_id + 1
    assert ledger.verify_chain() is True


# --- KG --------------------------------------------------------------------


def test_kg_add_edge_validates_endpoints() -> None:
    kg = KnowledgeGraphStub()
    src = kg.add_node("signal", {"k": 1})
    dst = kg.add_node("contact", {"k": 2})
    edge_id = kg.add_edge(src, dst, "RELATED_TO")
    assert edge_id in kg.edges
    with pytest.raises(ValueError):
        kg.add_edge(src, "nonexistent", "LINK")


# --- Matching overlap gate -------------------------------------------------


def test_matching_returns_no_candidates_without_overlap() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contact = Contact(
        contact_id=uuid4(),
        contact_type="INVESTOR",
        name="No Overlap",
        organization="Acme",
        focus_areas=["999-totally-different"],
        stated_thesis_tags=["nothing-matches"],
        warm_signal_score=100,
        under_nda=False,
        source_provenance={"seed_source": "TEST"},
    )
    engine = MatchingEngine(taxonomy=taxonomy, contacts=[contact])
    bus = InMemoryBus()
    event = IngestionPipeline(bus, taxonomy).ingest(
        RawSignal(
            source="telegram",
            source_url="telegram://t",
            raw_text="Stem cell longevity clinical regenerative update",
            topics=["telegram"],
        )
    )
    assert event is not None
    results = engine.match_external_signal(event)
    assert results == []


# --- HITL ------------------------------------------------------------------


def test_approval_queue_raises_typed_not_found() -> None:
    queue = ApprovalQueue()
    with pytest.raises(DraftNotFound):
        queue.approve(uuid4(), "x@y.com", "principal_investigator")


# --- Sender ----------------------------------------------------------------


class _FakeFailingResend:
    def send(self, *, to: str, subject: str, html_body: str):
        from services.outreach.resend_client import ResendSendResult

        return ResendSendResult(
            email_id=None,
            to=to,
            subject=subject,
            mode="sandbox",
            success=False,
            error="boom",
        )


def test_sender_does_not_mark_sent_when_resend_fails() -> None:
    queue = ApprovalQueue()
    record = queue.draft("body", {"principal_investigator"})
    token = queue.approve(
        record.draft_id, "mock_pi@longevityintime.org", "principal_investigator"
    )
    sender = OutreachSender(queue, resend_client=_FakeFailingResend())
    result = sender.send_email(
        record.draft_id,
        token=token,
        to_email="x@example.com",
        subject="s",
        html_body="<p>hi</p>",
    )
    from packages.hitl.queue import ApprovalState

    assert result.delivered is False
    assert result.error == "boom"
    assert queue.records[record.draft_id].state == ApprovalState.APPROVED


# --- Pipeline dedup --------------------------------------------------------


def test_pipeline_insert_first_dedup_returns_none_on_duplicate() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    pipeline = IngestionPipeline(InMemoryBus(), taxonomy)
    raw = RawSignal(
        source="telegram",
        source_url="telegram://t",
        raw_text="Longevity clinical trial signal",
        topics=["longevity"],
    )
    first = pipeline.ingest(raw)
    second = pipeline.ingest(raw)
    assert first is not None
    assert second is None
