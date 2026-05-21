import pytest

from packages.bus.memory import InMemoryBus
from packages.common.schemas import EventEnvelope
from packages.hitl import ApprovalQueue, load_reviewers
from packages.ledger.chain import Ledger
from services.specialists import specialist_agents
from services.specialists.agents import wire_all_agents

import uuid


def test_all_six_specialist_agents_are_registered() -> None:
    agents = specialist_agents()

    assert {agent.topic for agent in agents} == {
        "specialist_request.grant",
        "specialist_request.preprint",
        "specialist_request.journal",
        "specialist_request.patent",
        "specialist_request.dua",
        "specialist_request.fda",
    }


@pytest.mark.parametrize("agent", specialist_agents())
def test_specialist_drafts_enter_approval_queue_with_header(agent) -> None:
    queue = ApprovalQueue()

    draft_id = agent.draft("Draft package", queue)

    record = queue.records[draft_id]
    assert record.content.startswith("AI-DRAFTED - NOT FOR SUBMISSION WITHOUT")
    assert record.required_roles == agent.required_roles


@pytest.mark.parametrize("agent", specialist_agents())
def test_specialist_real_portal_sends_are_hard_disabled(agent) -> None:
    with pytest.raises(NotImplementedError):
        agent.submit_to_real_portal(payload={"demo": True})


@pytest.mark.parametrize("agent", specialist_agents())
def test_specialist_portal_send_validates_parameters_before_disable(agent) -> None:
    with pytest.raises(ValueError):
        agent.submit_to_real_portal()


def test_bus_event_triggers_auto_draft() -> None:
    """A bus event on specialist_request.grant should create a draft in the queue."""
    bus = InMemoryBus()
    queue = ApprovalQueue()
    ledger = Ledger()

    wire_all_agents(bus, queue, ledger=ledger)

    envelope = EventEnvelope(
        event_id=uuid.uuid4(),
        topic="specialist_request.grant",
        payload={"request": "NIH R01 application for longevity biomarker study"},
        provenance_hash=None,
    )
    bus.publish(envelope)

    # One draft should now be in the queue
    drafts = [
        r for r in queue.records.values()
        if "grants_administrator" in r.required_roles
    ]
    assert len(drafts) == 1
    assert "AI-DRAFTED" in drafts[0].content
    # Ledger should have the specialist_draft record
    ledger_types = [r.record_type for r in ledger.records]
    assert "specialist_draft" in ledger_types


@pytest.mark.parametrize("agent", specialist_agents())
def test_wrong_role_rejection_uses_loaded_reviewers(agent) -> None:
    """Wrong-role approval should fail even when approver identity comes from reviewers.json."""
    reviewers = load_reviewers()
    queue = ApprovalQueue()
    draft_id = agent.draft("test request", queue)

    # Find a reviewer whose role does NOT match this agent's required roles
    wrong_reviewer = next(
        (r for r in reviewers if r.role not in agent.required_roles),
        None,
    )
    if wrong_reviewer is None:
        pytest.skip("No wrong-role reviewer available for this agent")

    with pytest.raises(PermissionError):
        queue.approve(draft_id, wrong_reviewer.email, wrong_reviewer.role)


@pytest.mark.parametrize("agent", specialist_agents())
def test_correct_role_approval_succeeds_with_loaded_reviewers(agent) -> None:
    """Correct-role approval should succeed with a real reviewer identity from reviewers.json."""
    reviewers = load_reviewers()
    queue = ApprovalQueue()
    draft_id = agent.draft("test request", queue)

    # Find a reviewer whose role matches
    correct_reviewer = next(
        (r for r in reviewers if r.role in agent.required_roles),
        None,
    )
    if correct_reviewer is None:
        pytest.skip("No correct-role reviewer available for this agent in reviewers.json")

    token = queue.approve(draft_id, correct_reviewer.email, correct_reviewer.role)
    assert token.reviewer_identity == correct_reviewer.email
    assert token.reviewer_role == correct_reviewer.role
