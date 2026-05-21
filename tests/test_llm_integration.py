from pathlib import Path

from packages.bus import InMemoryBus
from packages.common.schemas import ConfidentialityTier
from packages.llm import MockLLMClient, build_llm_client
from packages.taxonomy import load_taxonomy
from services.ingestion import IngestionPipeline
from services.ingestion.sources import telegram_signal
from services.matching import MatchingEngine
from services.matching.contacts import load_contacts
from services.matching.milestones import publish_manual_milestone
from services.matching.redaction import redact_for_llm
from services.outreach import OutreachDraftingService
from apps.dashboard.app import _build_dashboard_llm


def test_llm_factory_defaults_to_mock() -> None:
    client = build_llm_client("mock")

    assert client.complete("Hello").provider == "mock"


def test_dashboard_llm_builder_requires_key_for_real_provider() -> None:
    try:
        _build_dashboard_llm("Groq", "", "llama-3.3-70b-versatile")
    except ValueError as exc:
        assert "requires an API key" in str(exc)
    else:
        raise AssertionError("Expected real provider without key to fail")


def test_ingestion_uses_parser_llm_for_summary() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    pipeline = IngestionPipeline(InMemoryBus(), taxonomy, parser_llm=MockLLMClient())

    event = pipeline.ingest(telegram_signal("Longevity clinical brain update"))

    assert event is not None
    assert "Summarize this external longevity signal" in event.parsed_summary


def test_matching_uses_llm_for_rationale_without_changing_score() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    engine = MatchingEngine(taxonomy, contacts, rationale_llm=MockLLMClient())
    event = IngestionPipeline(InMemoryBus(), taxonomy).ingest(
        telegram_signal("Stem cell longevity clinical regenerative update")
    )

    matches = engine.match_external_signal(event)  # type: ignore[arg-type]

    assert matches[0].match_score > 0
    assert "Write a short plain-English rationale" in matches[0].match_rationale


def test_outreach_drafting_uses_llm_output_for_human_review_draft() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    engine = MatchingEngine(taxonomy, contacts)
    event = IngestionPipeline(InMemoryBus(), taxonomy).ingest(
        telegram_signal("Stem cell longevity clinical regenerative update")
    )
    match = engine.match_external_signal(event)[0]  # type: ignore[arg-type]

    draft = OutreachDraftingService(MockLLMClient()).draft_email(match)

    assert "Hi " in draft
    assert "Would you be open" in draft


def test_investor_nda_redaction_happens_before_llm_prompt() -> None:
    event = publish_manual_milestone("3", "NDA endpoint", ConfidentialityTier.INVESTOR_NDA)

    redacted = redact_for_llm(event.model_dump(mode="json"))

    assert redacted["summary"] == "[REDACTED_INVESTOR_NDA]"
    assert redacted["narrative_for_outreach"] == "[REDACTED_INVESTOR_NDA]"
    assert redacted["supporting_evidence_refs"] == []

