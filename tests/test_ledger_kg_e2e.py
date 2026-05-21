"""Ledger, KG, and full mocked E2E happy path tests.

All tests use InMemoryBus and in-memory Ledger/KG so no Postgres or Redis
instance is required. The architecture supports swapping to real backends via
env vars (BUS_BACKEND=redis, LEDGER_SQLITE_PATH, KG_SQLITE_PATH).
"""
from pathlib import Path
from uuid import uuid4

from packages.bus import InMemoryBus
from packages.common.schemas import EventEnvelope
from packages.hitl import ApprovalQueue, load_reviewers
from packages.kg import KnowledgeGraphStub
from packages.ledger import Ledger
from packages.taxonomy import load_taxonomy
from services.ingestion import IngestionPipeline
from services.ingestion.sources import telegram_signal
from services.matching import MatchingEngine
from services.matching.contacts import load_contacts
from services.outreach import OutreachSender
from services.specialists.agents import wire_all_agents


def test_ledger_verifies_seeded_chain() -> None:
    ledger = Ledger()
    ledger.append("external_signal", {"event_id": "demo"})
    ledger.append("candidate_emitted", {"candidate_id": "demo"})

    assert ledger.verify_chain() is True


def test_ledger_last_n_returns_recent_records() -> None:
    ledger = Ledger()
    for i in range(5):
        ledger.append("test_event", {"i": i})
    last = ledger.last_n(3)
    assert len(last) == 3
    assert last[-1].record_type == "test_event"


def test_kg_stub_accepts_event_and_contact_nodes() -> None:
    kg = KnowledgeGraphStub()

    event_node = kg.add_node("external_signal", {"event_id": "demo"})
    contact_node = kg.add_node("contact", {"contact_id": "demo"})

    assert kg.nodes[event_node]["node_type"] == "external_signal"
    assert kg.nodes[contact_node]["node_type"] == "contact"


def test_kg_stub_add_edge() -> None:
    kg = KnowledgeGraphStub()
    n1 = kg.add_node("signal", {"id": "s1"})
    n2 = kg.add_node("contact", {"id": "c1"})
    edge_id = kg.add_edge(n1, n2, "matched")
    assert edge_id  # just confirms no exception


def test_mocked_e2e_happy_path() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    bus = InMemoryBus()
    ledger = Ledger()
    kg = KnowledgeGraphStub()

    event = IngestionPipeline(bus, taxonomy).ingest(
        telegram_signal("Stem cell longevity clinical regenerative update")
    )
    assert event is not None
    ledger.append("external_signal", event.model_dump(mode="json"))
    kg.add_node("external_signal", event.model_dump(mode="json"))

    matches = MatchingEngine(taxonomy, contacts, bus=bus).match_external_signal(event)
    candidate = next(match for match in matches if match.suppressed_reason is None)
    ledger.append("candidate_emitted", {"candidate_id": str(candidate.candidate_id)})

    queue = ApprovalQueue()
    draft = queue.draft("Draft outreach email", {"principal_investigator"})
    token = queue.approve(draft.draft_id, "mock_pi@longevityintime.org", "principal_investigator")
    ledger.append("approval_token_issued", {"draft_id": str(draft.draft_id)})

    result = OutreachSender(queue).send_email(draft.draft_id, token)
    ledger.append("message_sent", {"draft_id": str(result.draft_id)})

    assert result.delivered is True
    assert ledger.verify_chain() is True

    # Bus should have: signal event + candidate events
    topics = [e.topic for e in bus.published]
    assert any(t.startswith("external_signal.") for t in topics)
    assert any(t.startswith("outreach_candidate.") for t in topics)


def test_specialist_bus_wiring_creates_draft_and_ledger_entry() -> None:
    bus = InMemoryBus()
    queue = ApprovalQueue()
    ledger = Ledger()

    wire_all_agents(bus, queue, ledger=ledger)

    # Publish a grant specialist request event
    bus.publish(EventEnvelope(
        event_id=uuid4(),
        topic="specialist_request.grant",
        payload={"request": "NIH R01 longevity biomarker"},
        provenance_hash=None,
    ))

    # One draft should exist
    drafts = [r for r in queue.records.values() if "grants_administrator" in r.required_roles]
    assert len(drafts) == 1

    # Ledger should record it
    assert any(r.record_type == "specialist_draft" for r in ledger.records)
    assert ledger.verify_chain() is True


def test_e2e_reply_intent_triggers_handling() -> None:
    """Full loop: approve → send → classify reply intent."""
    queue = ApprovalQueue()
    draft = queue.draft("Draft email body", {"principal_investigator"})
    token = queue.approve(draft.draft_id, "mock_pi@longevityintime.org", "principal_investigator")
    sender = OutreachSender(queue)
    result = sender.send_email(draft.draft_id, token)
    assert result.delivered is True

    intent = sender.classify_reply_intent("I'd like to schedule a meeting to discuss further.")
    assert intent == "meeting_requested"


def test_nda_text_never_reaches_llm() -> None:
    """INVESTOR_NDA body text must be redacted before LLM calls."""
    from services.matching.redaction import redact_for_llm
    from packages.common.schemas import ConfidentialityTier

    event_dict = {
        "confidentiality_tier": ConfidentialityTier.INVESTOR_NDA.value,
        "summary": "Top-secret investor roadmap details",
        "narrative_for_outreach": "Sensitive investor content",
        "parsed_summary": "Public-facing summary",
    }
    safe = redact_for_llm(event_dict)
    assert safe["summary"] == "[REDACTED_INVESTOR_NDA]"
    assert safe["narrative_for_outreach"] == "[REDACTED_INVESTOR_NDA]"
    # parsed_summary is not in the redaction list – it stays
    assert "secret" not in safe.get("summary", "")


def test_reviewers_loaded_and_cover_all_specialist_roles() -> None:
    from services.specialists import specialist_agents

    reviewers = load_reviewers()
    reviewer_roles = {r.role for r in reviewers}
    agents = specialist_agents()
    for agent in agents:
        covered = any(role in reviewer_roles for role in agent.required_roles)
        assert covered, f"No reviewer covers required role(s) for {agent.name}: {agent.required_roles}"
