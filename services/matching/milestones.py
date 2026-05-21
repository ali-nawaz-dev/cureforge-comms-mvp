"""Manual internal milestone publisher.

Can be used as a library or run as a CLI:
  python -m services.matching.milestones --institute-id 3 --title "..." --tier PUBLIC
"""
from __future__ import annotations

from uuid import uuid4

from packages.common.hashing import canonical_json, sha256_hex
from packages.common.schemas import ConfidentialityTier, EventEnvelope, InternalMilestoneEvent
from packages.common.time import utc_now_iso


def publish_manual_milestone(
    institute_id: str,
    title: str,
    confidentiality_tier: ConfidentialityTier = ConfidentialityTier.PUBLIC,
    bus=None,
) -> InternalMilestoneEvent:
    payload = {
        "institute_id": institute_id,
        "title": title,
        "confidentiality_tier": confidentiality_tier.value,
    }
    now = utc_now_iso()
    event = InternalMilestoneEvent(
        event_id=uuid4(),
        milestone_type="OTHER",
        institute_id=institute_id,
        title=title,
        summary=f"Manual milestone: {title}",
        narrative_for_outreach=f"External-safe narrative for {title}",
        supporting_evidence_refs=[],
        confidentiality_tier=confidentiality_tier,
        occurred_at=now,
        ingest_timestamp=now,
        provenance_hash=sha256_hex(canonical_json(payload)),
    )
    if bus is not None:
        bus.publish(
            EventEnvelope(
                event_id=event.event_id,
                topic=f"internal_milestone.{confidentiality_tier.value.lower()}.{institute_id}",
                payload=event.model_dump(mode="json"),
                provenance_hash=event.provenance_hash,
            )
        )
    return event


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Publish a manual internal milestone to the bus."
    )
    parser.add_argument("--institute-id", required=True, help="Taxonomy institute ID (e.g. 3)")
    parser.add_argument("--title", required=True, help="Human-readable milestone title")
    parser.add_argument(
        "--tier",
        default="PUBLIC",
        choices=[t.value for t in ConfidentialityTier],
        help="Confidentiality tier (default: PUBLIC)",
    )
    args = parser.parse_args()

    from packages.bus.factory import get_bus
    from packages.common.logging import configure_json_logging

    configure_json_logging()
    bus = get_bus()
    event = publish_manual_milestone(
        institute_id=args.institute_id,
        title=args.title,
        confidentiality_tier=ConfidentialityTier(args.tier),
        bus=bus,
    )
    print(f"Published milestone: event_id={event.event_id}  tier={event.confidentiality_tier.value}")


if __name__ == "__main__":
    _cli()
