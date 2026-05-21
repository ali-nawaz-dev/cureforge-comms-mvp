#!/usr/bin/env python3
"""Live Redis-bus E2E walkthrough (ingest → match → draft → approve → send → reply).

Prerequisites:
  - Redis running (``make docker-up`` or ``redis-server``)
  - ``REDIS_URL`` and ``BUS_BACKEND=redis`` in the environment

Run::

    PYTHONPATH=. BUS_BACKEND=redis REDIS_URL=redis://localhost:6379/0 python3.11 scripts/redis_bus_e2e.py

The script prints each bus topic as it fires so you can record or follow along live.
Inbound reply classification uses the dashboard's simulated path (MX not required).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from packages.bus.factory import get_bus
from packages.common.schemas import EventEnvelope, ExternalSignalEvent, InstituteClassification
from packages.hitl import ApprovalQueue
from packages.ledger.chain import Ledger
from packages.taxonomy import load_taxonomy
from services.matching import MatchingEngine
from services.matching.contacts import load_contacts
from services.matching.worker import MatcherWorker
from services.outreach import OutreachSender
from services.outreach.worker import OutreachWorker


def _log(topic: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[bus] {topic}{suffix}")


def main() -> int:
    os.environ.setdefault("BUS_BACKEND", "redis")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

    bus = get_bus()
    root = Path(__file__).resolve().parents[1]
    taxonomy = load_taxonomy(root / "data/taxonomy_v0_2.json")
    contacts = load_contacts(root / "data/seeds/contacts.json")
    queue = ApprovalQueue(bus=bus)
    ledger = Ledger()
    engine = MatchingEngine(taxonomy=taxonomy, contacts=contacts)

    seen: list[str] = []

    def tap(envelope: EventEnvelope) -> None:
        seen.append(envelope.topic)
        _log(envelope.topic, str(envelope.payload.get("draft_id", ""))[:36])

    for pattern in (
        "external_signal.*",
        "outreach_candidate.*",
        "outreach_draft.*",
        "approval.*",
        "message.*",
        "dlq.*",
    ):
        bus.subscribe(pattern, tap)

    matcher = MatcherWorker(bus, engine, ledger=ledger)
    outreach = OutreachWorker(bus, queue, contacts, ledger=ledger)
    matcher.start()
    outreach.start()

    event = ExternalSignalEvent(
        event_id=uuid4(),
        source="telegram",
        source_url="telegram://e2e-demo",
        ingest_timestamp="2026-05-20T12:00:00Z",
        content_hash="b" * 64,
        parsed_summary="stem cell longevity clinical trial update",
        institutes=[InstituteClassification(institute_id="48", confidence=0.9)],
        topics=["longevity"],
        raw_text_ref="raw:e2e",
        classifier_confidence=0.85,
        parser_confidence=0.85,
        provenance_hash="demo",
    )
    envelope = EventEnvelope(
        event_id=event.event_id,
        topic="external_signal.telegram.48",
        payload=event.model_dump(mode="json"),
    )

    print("Publishing external_signal…")
    bus.publish(envelope)
    time.sleep(1.5)

    if not any(t.startswith("outreach_candidate.") for t in seen):
        print("ERROR: no outreach_candidate.* event — check matching/contacts", file=sys.stderr)
        return 1

    draft_id = next(iter(queue.records))
    record = queue.records[draft_id]
    print(f"Draft {draft_id} in queue (state={record.state.value})")

    token = queue.approve(
        draft_id, "mock_pi@longevityintime.org", "principal_investigator"
    )
    print("Approved.")

    result = OutreachSender(queue, mode="sandbox").send_email(draft_id, token)
    print(f"Send result: delivered={result.delivered} mode={result.mode}")

    intent, new_token = OutreachSender(queue).handle_inbound_reply(
        text="Can we schedule a meeting next week?",
        contact_id="e2e-demo-contact",
    )
    print(f"Reply intent: {intent}; token refreshed={new_token is not None}")

    bus.close()
    print("\nTopics observed:", ", ".join(seen))
    required = {"outreach_draft.created", "message.sent"}
    missing = required - set(seen)
    if missing:
        print(f"WARNING: expected topics not seen: {missing}", file=sys.stderr)
        return 1
    print("Redis E2E walkthrough complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
