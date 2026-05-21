"""Tests for active_conversation_token lifecycle.

Rules under test:
- intent ∈ {interested, needs_info, meeting_requested, needs_review} → issue/refresh token
- intent == not_interested → revoke immediately
- TTL 30 days from issuance; expired tokens do not bypass cooldown
- is_token_valid() returns True for valid, False for expired/None/malformed
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from packages.hitl.conversation_token import (
    handle_reply_token,
    is_token_valid,
    issue_token,
    parse_token,
    token_contact_id,
    token_expiry,
)


def test_issue_token_is_signed_and_parseable() -> None:
    token = issue_token("contact-123")
    payload = parse_token(token)
    assert payload is not None
    assert payload["contact_id"] == "contact-123"
    exp = datetime.fromisoformat(payload["exp"])
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp > datetime.now(timezone.utc)
    assert exp <= datetime.now(timezone.utc) + timedelta(days=31)


def test_issue_token_handles_contact_id_with_colon() -> None:
    token = issue_token("contact:weird:id")
    assert token_contact_id(token) == "contact:weird:id"
    assert is_token_valid(token)


def test_token_valid_for_fresh_issue() -> None:
    token = issue_token("c1")
    assert is_token_valid(token) is True


def test_token_invalid_when_expired() -> None:
    token = issue_token("c-expiring", ttl_days=-1)
    assert is_token_valid(token) is False


def test_token_invalid_for_none() -> None:
    assert is_token_valid(None) is False


def test_token_invalid_for_malformed() -> None:
    assert is_token_valid("bad-token-no-date") is False


def test_token_invalid_for_tampered_payload() -> None:
    token = issue_token("c-tamper")
    parts = token.split(".")
    # Truncate the payload portion; the signature now mismatches.
    tampered = parts[0][:-2] + "." + parts[1]
    assert is_token_valid(tampered) is False


def test_token_expiry_helper_returns_iso() -> None:
    token = issue_token("c-exp")
    exp = token_expiry(token)
    assert exp is not None
    parsed = datetime.fromisoformat(exp)
    assert parsed.tzinfo is not None


@pytest.mark.parametrize("intent", ["meeting_requested", "interested", "needs_info", "needs_review"])
def test_handle_reply_issues_token_for_active_intents(intent: str) -> None:
    new_token = handle_reply_token("contact-1", intent, current_token=None)
    assert new_token is not None
    assert is_token_valid(new_token)


def test_handle_reply_revokes_token_on_not_interested() -> None:
    existing_token = issue_token("contact-2")
    new_token = handle_reply_token("contact-2", "not_interested", current_token=existing_token)
    assert new_token is None


def test_handle_reply_refreshes_existing_token() -> None:
    old_token = issue_token("contact-3")
    new_token = handle_reply_token("contact-3", "meeting_requested", current_token=old_token)
    assert new_token is not None
    assert is_token_valid(new_token)
    # New token should have a fresh expiry (same or later instant).
    old_exp = datetime.fromisoformat(token_expiry(old_token))  # type: ignore[arg-type]
    new_exp = datetime.fromisoformat(token_expiry(new_token))  # type: ignore[arg-type]
    assert new_exp >= old_exp


def test_cooldown_bypassed_when_valid_token_present() -> None:
    """Matching engine suppression check must not suppress contacts with valid tokens."""
    from services.matching.engine import Contact, MatchingEngine
    from packages.taxonomy import load_taxonomy
    from pathlib import Path
    from datetime import date as dt

    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    fresh_token = issue_token("c-test")
    contact = Contact(
        contact_id=__import__("uuid").uuid4(),
        contact_type="INVESTOR",
        name="Test Investor",
        organization="TestCo",
        focus_areas=["3"],
        stated_thesis_tags=["longevity"],
        warm_signal_score=50,
        under_nda=False,
        source_provenance={},
        disinterest_flag=False,
        last_contact_from_us_date=(dt.today() - __import__("datetime").timedelta(days=10)).isoformat(),
        active_conversation_token=fresh_token,
    )
    engine = MatchingEngine(taxonomy=taxonomy, contacts=[contact])
    reason = engine._suppression_reason(contact)
    assert reason is None, "Valid token should bypass 60-day cooldown"


def test_cooldown_enforced_when_token_expired() -> None:
    """Expired token should NOT bypass cooldown."""
    from services.matching.engine import Contact, MatchingEngine
    from packages.taxonomy import load_taxonomy
    from pathlib import Path
    from datetime import date as dt

    taxonomy = load_taxonomy(Path("data/taxonomy_v0_2.json"))
    expired_token = issue_token("c-exp", ttl_days=-1)
    contact = Contact(
        contact_id=__import__("uuid").uuid4(),
        contact_type="INVESTOR",
        name="Expired Token Investor",
        organization="TestCo",
        focus_areas=["3"],
        stated_thesis_tags=["longevity"],
        warm_signal_score=50,
        under_nda=False,
        source_provenance={},
        disinterest_flag=False,
        last_contact_from_us_date=(dt.today() - __import__("datetime").timedelta(days=10)).isoformat(),
        active_conversation_token=expired_token,
    )
    engine = MatchingEngine(taxonomy=taxonomy, contacts=[contact])
    reason = engine._suppression_reason(contact)
    assert reason == "cooldown_60_days"


def test_sender_cooldown_bypassed_with_valid_token() -> None:
    """OutreachSender._in_cooldown must return False when token is valid."""
    from services.outreach.sender import OutreachSender
    from packages.hitl import ApprovalQueue

    sender = OutreachSender(ApprovalQueue())
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    valid_token = issue_token("contact-send-test")
    assert sender._in_cooldown(recent_date, valid_token) is False


def test_sender_cooldown_enforced_without_token() -> None:
    from services.outreach.sender import OutreachSender
    from packages.hitl import ApprovalQueue

    sender = OutreachSender(ApprovalQueue())
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    assert sender._in_cooldown(recent_date, None) is True
