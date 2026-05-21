"""Specialist drafting agents.

Each agent:
- Listens to its bus topic (specialist_request.<name>) passively via bus.subscribe()
- Auto-drafts on receipt and places output in the approval queue
- Logs every draft, approval token, and submission attempt to the ledger
- Hard-disables real portal sends (NotImplementedError)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from packages.hitl import ApprovalQueue

logger = logging.getLogger(__name__)

AI_DRAFTED_HEADER = "AI-DRAFTED - NOT FOR SUBMISSION WITHOUT {role} REVIEW"


@dataclass(frozen=True)
class SpecialistAgent:
    name: str
    topic: str
    required_roles: set[str]
    portal_name: str

    def draft(self, request: str, queue: ApprovalQueue, ledger=None) -> UUID:
        role_label = " OR ".join(sorted(self.required_roles))
        content = f"{AI_DRAFTED_HEADER.format(role=role_label)}\n\n{request}"
        record = queue.draft(content, self.required_roles)
        if ledger:
            ledger.append("specialist_draft", {
                "agent": self.name,
                "topic": self.topic,
                "draft_id": str(record.draft_id),
            })
        logger.info(
            "Specialist draft created",
            extra={"agent": self.name, "draft_id": str(record.draft_id)},
        )
        return record.draft_id

    def subscribe_to_bus(self, bus, queue: ApprovalQueue, ledger=None) -> None:
        """Register a bus handler so this agent auto-drafts on incoming events.

        Each agent keeps its own ``IdempotencyCache`` so a Redis redelivery of
        the same ``specialist_request.*`` event does not create a duplicate
        draft.
        """
        from packages.bus.idempotency import IdempotencyCache

        cache = IdempotencyCache()

        def _handler(envelope) -> None:
            if not cache.claim(str(envelope.event_id)):
                return
            try:
                payload = envelope.payload
                request_text = payload.get("request", payload.get("body", str(payload)))
                self.draft(request_text, queue, ledger=ledger)
                logger.info(
                    "Specialist auto-draft triggered",
                    extra={"agent": self.name, "event_id": str(envelope.event_id)},
                )
            except Exception as exc:
                logger.error("Specialist bus handler error (%s): %s", self.name, exc)

        bus.subscribe(self.topic, _handler)
        logger.info("Agent %s subscribed to bus topic %s", self.name, self.topic)

    def submit_to_real_portal(self, **kwargs: object) -> None:
        if not kwargs:
            raise ValueError("Portal submission parameters are required for validation")
        if ledger := kwargs.pop("_ledger", None):
            ledger.append("specialist_portal_attempt_blocked", {
                "agent": self.name,
                "portal": self.portal_name,
            })
        raise NotImplementedError(f"{self.portal_name} submission is hard-disabled for MVP")


def specialist_agents() -> list[SpecialistAgent]:
    return [
        SpecialistAgent(
            "Grant Agent", "specialist_request.grant", {"grants_administrator"}, "Grants.gov"
        ),
        SpecialistAgent(
            "Preprint Agent",
            "specialist_request.preprint",
            {"principal_investigator"},
            "arXiv SWORD",
        ),
        SpecialistAgent(
            "Journal Agent",
            "specialist_request.journal",
            {"principal_investigator"},
            "Editorial Manager",
        ),
        SpecialistAgent(
            "Patent Agent", "specialist_request.patent", {"patent_counsel"}, "USPTO"
        ),
        SpecialistAgent(
            "DUA Agent",
            "specialist_request.dua",
            {"regulatory_advisor", "institutional_legal"},
            "DUA portal",
        ),
        SpecialistAgent(
            "FDA Agent", "specialist_request.fda", {"regulatory_advisor"}, "FDA ESG"
        ),
    ]


def wire_all_agents(bus, queue: ApprovalQueue, ledger=None) -> list[SpecialistAgent]:
    """Subscribe all specialist agents to their bus topics. Returns agent list."""
    agents = specialist_agents()
    for agent in agents:
        agent.subscribe_to_bus(bus, queue, ledger=ledger)
    return agents
