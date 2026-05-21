from pathlib import Path

from packages.common.schemas import ConfidentialityTier, InstituteClassification
from packages.taxonomy import load_taxonomy
from services.ingestion.sources import telegram_signal
from services.ingestion.pipeline import IngestionPipeline
from packages.bus import InMemoryBus
from services.matching import MatchingEngine
from services.matching.contacts import load_contacts
from services.matching.milestones import publish_manual_milestone
from services.matching.redaction import redact_for_llm


def _engine() -> MatchingEngine:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    contacts = load_contacts(Path("data/seeds/contacts.json"))
    return MatchingEngine(taxonomy=taxonomy, contacts=contacts)


def test_synthetic_contacts_are_loaded_and_labeled() -> None:
    contacts = load_contacts(Path("data/seeds/contacts.json"))

    assert len(contacts) == 25
    assert {contact.contact_type for contact in contacts} == {
        "INVESTOR",
        "GRANT_OFFICER",
        "KOL",
        "PARTNER",
        "DATA_CUSTODIAN",
    }
    assert all(contact.source_provenance["seed_source"] == "SYNTHETIC_DEMO" for contact in contacts)


def test_matching_score_is_deterministic_and_llm_independent() -> None:
    engine = _engine()
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    event = IngestionPipeline(bus, taxonomy).ingest(
        telegram_signal("Stem cell longevity clinical regenerative update")
    )

    first = engine.match_external_signal(event)  # type: ignore[arg-type]
    second = engine.match_external_signal(event)  # type: ignore[arg-type]

    assert [item.match_score for item in first] == [item.match_score for item in second]


def test_resolve_taxonomy_suppresses_candidate_emission() -> None:
    engine = _engine()
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    event = IngestionPipeline(bus, taxonomy).ingest(telegram_signal("Longevity clinical update"))
    event.institutes = [InstituteClassification(institute_id="4", confidence=0.9)]  # type: ignore[union-attr]

    results = engine.match_external_signal(event)  # type: ignore[arg-type]

    assert results[0].suppressed_reason == "taxonomy_resolve_pending"


def test_internal_only_milestone_never_reaches_matching() -> None:
    engine = _engine()
    event = publish_manual_milestone("3", "Internal-only endpoint", ConfidentialityTier.INTERNAL_ONLY)

    assert engine.match_internal_milestone(event) == []


def test_investor_nda_matches_only_nda_contacts_and_redacts_llm_payload() -> None:
    engine = _engine()
    event = publish_manual_milestone("3", "NDA endpoint", ConfidentialityTier.INVESTOR_NDA)

    results = engine.match_internal_milestone(event)
    redacted = redact_for_llm(event.model_dump(mode="json"))

    assert all(result.contact.under_nda for result in results if not result.suppressed_reason)
    assert redacted["summary"] == "[REDACTED_INVESTOR_NDA]"
    assert redacted["narrative_for_outreach"] == "[REDACTED_INVESTOR_NDA]"

