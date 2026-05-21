from datetime import date

import pytest

from packages.hitl import ApprovalQueue
from services.outreach import OutreachSender


def test_approval_queue_rejects_wrong_role() -> None:
    queue = ApprovalQueue()
    record = queue.draft("Patent draft", {"patent_counsel"})

    with pytest.raises(PermissionError):
        queue.approve(record.draft_id, "mock_pi@longevityintime.org", "principal_investigator")


def test_sender_requires_valid_approved_token() -> None:
    queue = ApprovalQueue()
    record = queue.draft("Outreach draft", {"principal_investigator"})
    sender = OutreachSender(queue)

    with pytest.raises(PermissionError):
        sender.send_email(record.draft_id, token=None)

    token = queue.approve(record.draft_id, "mock_pi@longevityintime.org", "principal_investigator")
    result = sender.send_email(record.draft_id, token=token)

    assert result.delivered is True
    assert result.mode == "sandbox"


def test_sender_rechecks_cooldown_at_send_time() -> None:
    queue = ApprovalQueue()
    record = queue.draft("Outreach draft", {"principal_investigator"})
    token = queue.approve(record.draft_id, "mock_pi@longevityintime.org", "principal_investigator")
    sender = OutreachSender(queue)

    with pytest.raises(PermissionError):
        sender.send_email(record.draft_id, token=token, last_contact_from_us_date=date.today().isoformat())


def test_reply_classifier_detects_meeting_requested() -> None:
    sender = OutreachSender(ApprovalQueue())

    assert sender.classify_reply_intent("Can we schedule a meeting next week?") == "meeting_requested"

