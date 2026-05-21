"""Phase 5: concurrency tests."""
from __future__ import annotations

import threading
from pathlib import Path

from packages.bus import InMemoryBus
from packages.hitl import ApprovalQueue
from packages.hitl.queue import ApprovalState
from packages.taxonomy import load_taxonomy
from services.ingestion.pipeline import IngestionPipeline, RawSignal


def test_pipeline_ingest_under_concurrency_produces_single_event() -> None:
    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    pipeline = IngestionPipeline(InMemoryBus(), taxonomy)
    signal = RawSignal(
        source="telegram",
        source_url="telegram://t",
        raw_text="Stem cell longevity clinical trial",
        topics=["longevity"],
    )

    results: list = []
    lock = threading.Lock()

    def ingest_one() -> None:
        event = pipeline.ingest(signal)
        with lock:
            results.append(event)

    threads = [threading.Thread(target=ingest_one) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    accepted = [r for r in results if r is not None]
    duplicates = [r for r in results if r is None]
    assert len(accepted) == 1, "Insert-first dedup must elect a single winner"
    assert len(duplicates) == len(results) - 1


def test_hitl_queue_concurrent_approvals_are_consistent() -> None:
    queue = ApprovalQueue()
    record = queue.draft("hello", {"principal_investigator"})

    barrier = threading.Barrier(5)
    errors: list[Exception] = []
    successes: list = []
    lock = threading.Lock()

    def approve_once() -> None:
        barrier.wait()
        try:
            token = queue.approve(record.draft_id, "pi@x", "principal_investigator")
            with lock:
                successes.append(token)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=approve_once) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_state = queue.records[record.draft_id].state
    assert final_state == ApprovalState.APPROVED
    # The first approve transitions the state; all subsequent calls must
    # raise a ValueError ("Only awaiting approval records can be approved").
    assert len(successes) == 1
    assert all(isinstance(e, ValueError) for e in errors)
