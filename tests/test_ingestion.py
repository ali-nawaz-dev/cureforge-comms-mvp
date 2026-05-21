from pathlib import Path

from packages.bus import InMemoryBus
from packages.taxonomy import load_taxonomy
from services.ingestion import IngestionPipeline
from services.ingestion.sources import clinical_trials_signal, pubmed_signal, telegram_signal


def _pipeline() -> tuple[IngestionPipeline, InMemoryBus]:
    bus = InMemoryBus()
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    return IngestionPipeline(bus=bus, taxonomy=taxonomy), bus


def test_ingestion_publishes_external_signal_event() -> None:
    pipeline, bus = _pipeline()

    event = pipeline.ingest(telegram_signal("Longevity brain clinical trial update"))

    assert event is not None
    assert bus.published[0].topic == "external_signal.telegram.13"


def test_ingestion_deduplicates_before_parsing() -> None:
    pipeline, bus = _pipeline()

    assert pipeline.ingest(telegram_signal("Longevity clinical trial")) is not None
    assert pipeline.ingest(telegram_signal(" longevity   clinical trial ")) is None
    assert len(bus.published) == 1


def test_ingestion_filters_irrelevant_items() -> None:
    pipeline, bus = _pipeline()

    assert pipeline.ingest(telegram_signal("Quarterly sports media update")) is None
    assert bus.published == []


def test_pubmed_and_clinical_trials_sources_share_output_interface() -> None:
    pipeline, bus = _pipeline()

    pipeline.ingest(pubmed_signal("Stem cell longevity", "Regenerative medicine clinical study"))
    pipeline.ingest(clinical_trials_signal("Clinical trial for longevity intervention"))

    assert [event.topic.split(".")[1] for event in bus.published] == [
        "pubmed",
        "clinicaltrials_gov",
    ]

