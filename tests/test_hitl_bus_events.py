"""HITL queue publishes approval.rejected and message.sent on the bus."""
from __future__ import annotations

from packages.bus import InMemoryBus
from packages.hitl import ApprovalQueue


def test_reject_publishes_approval_rejected() -> None:
    bus = InMemoryBus()
    queue = ApprovalQueue(bus=bus)
    record = queue.draft("Draft body", {"principal_investigator"})

    queue.reject(record.draft_id)

    rejected = [e for e in bus.published if e.topic == "approval.rejected"]
    assert len(rejected) == 1
    assert rejected[0].payload["draft_id"] == str(record.draft_id)
    assert rejected[0].payload["state"] == "REJECTED"


def test_mark_sent_publishes_message_sent() -> None:
    bus = InMemoryBus()
    queue = ApprovalQueue(bus=bus)
    record = queue.draft("Draft body", {"principal_investigator"})
    token = queue.approve(record.draft_id, "mock_pi@longevityintime.org", "principal_investigator")

    queue.mark_sent(record.draft_id, token, send_metadata={"mode": "sandbox", "provider": "resend"})

    sent = [e for e in bus.published if e.topic == "message.sent"]
    assert len(sent) == 1
    assert sent[0].payload["draft_id"] == str(record.draft_id)
    assert sent[0].payload["mode"] == "sandbox"
    assert sent[0].payload["provider"] == "resend"
